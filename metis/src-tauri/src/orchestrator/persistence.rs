//! SQLite persistence for pipeline results and signals.
//!
//! Pipeline results previously lived only in an in-memory HashMap — every
//! job's signals (and the execution-engine responses attached to them)
//! evaporated on process exit, so the UI had no history to show. This
//! module writes each completed (or failed) run to a local SQLite database:
//!
//! - `jobs`    one row per pipeline run, with phase timings and metrics
//! - `signals` one row per generated signal, including exec status reported
//!             by the Rust engine and the RAG explanation id
//!
//! The DB is a runtime artifact under `<project_root>/data/`, consistent
//! with the rest of the local data layout. All failures are non-fatal:
//! persistence problems are logged and the pipeline result still returns.

use super::types::{PipelineResult, TradingSignal};
use rusqlite::Connection;
use std::path::Path;
use std::sync::Mutex;
use tracing::{error, info, warn};

pub struct Persistence {
    conn: Mutex<Connection>,
}

impl Persistence {
    /// Open (creating if needed) the orchestrator database and ensure the
    /// schema exists.
    pub fn new(db_path: &Path) -> rusqlite::Result<Self> {
        if let Some(parent) = db_path.parent() {
            if let Err(e) = std::fs::create_dir_all(parent) {
                warn!(
                    "Could not create data dir {}: {}",
                    parent.display(),
                    e
                );
            }
        }

        let conn = Connection::open(db_path)?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS jobs (
                job_id            TEXT PRIMARY KEY,
                status            TEXT NOT NULL,
                phase             TEXT NOT NULL,
                mode              TEXT NOT NULL,
                total_time        REAL NOT NULL DEFAULT 0,
                ingest_time       REAL NOT NULL DEFAULT 0,
                feature_time      REAL NOT NULL DEFAULT 0,
                inference_time    REAL NOT NULL DEFAULT 0,
                signals_generated INTEGER NOT NULL DEFAULT 0,
                avg_confidence    REAL NOT NULL DEFAULT 0,
                error             TEXT,
                run_timestamp     TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS signals (
                signal_id        TEXT PRIMARY KEY,
                job_id           TEXT NOT NULL,
                symbol           TEXT NOT NULL,
                direction        TEXT NOT NULL,
                confidence       REAL NOT NULL,
                target_quantity  REAL NOT NULL,
                horizon_minutes  INTEGER NOT NULL,
                exec_status      TEXT,
                exec_latency_ms  INTEGER,
                exec_filled_qty  REAL,
                exec_slippage_bps REAL,
                explanation_id   TEXT,
                timestamp        TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(job_id)
            );
            CREATE INDEX IF NOT EXISTS idx_signals_timestamp
                ON signals(timestamp DESC);",
        )?;

        // Migrate pre-v1.1 databases: add the fill-quality columns if the
        // signals table predates them. "duplicate column name" errors are
        // the expected no-op case for fresh databases.
        let _ = conn.execute_batch("ALTER TABLE signals ADD COLUMN exec_filled_qty REAL;");
        let _ = conn.execute_batch("ALTER TABLE signals ADD COLUMN exec_slippage_bps REAL;");

        info!("Persistence ready at {}", db_path.display());
        Ok(Self {
            conn: Mutex::new(conn),
        })
    }

    /// Write a full pipeline result: upsert the job row, then replace this
    /// job's signal rows. One transaction — a partial write is worse than
    /// none.
    pub fn persist_result(&self, result: &PipelineResult) -> Result<(), String> {
        let mut conn = self.conn.lock().unwrap();
        let tx = conn.transaction().map_err(|e| e.to_string())?;

        tx.execute(
            "INSERT OR REPLACE INTO jobs (
                job_id, status, phase, mode, total_time, ingest_time,
                feature_time, inference_time, signals_generated,
                avg_confidence, error, run_timestamp
            ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)",
            rusqlite::params![
                result.job_id,
                result.status.to_string(),
                result.phase.to_string(),
                result.metrics.mode.to_string(),
                result.metrics.total_time,
                result.metrics.ingest_time,
                result.metrics.feature_time,
                result.metrics.inference_time,
                result.metrics.signals_generated,
                result.metrics.avg_confidence,
                result.error,
                result.metrics.run_timestamp.to_rfc3339(),
            ],
        )
        .map_err(|e| e.to_string())?;

        tx.execute("DELETE FROM signals WHERE job_id = ?1", [&result.job_id])
            .map_err(|e| e.to_string())?;

        for signal in &result.signals {
            if let Err(e) = persist_signal(&tx, &result.job_id, signal) {
                // One bad signal shouldn't lose the job row or its siblings.
                error!(
                    "Signal {} not persisted: {}",
                    signal.signal_id, e
                );
            }
        }

        tx.commit().map_err(|e| e.to_string())
    }

    /// Most recent signals, newest first. Returns JSON objects shaped like
    /// the in-memory TradingSignal plus exec/explanation fields.
    pub fn recent_signals(&self, limit: u32) -> Result<Vec<serde_json::Value>, String> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn
            .prepare(
                "SELECT signal_id, job_id, symbol, direction, confidence,
                        target_quantity, horizon_minutes, exec_status,
                        exec_latency_ms, exec_filled_qty, exec_slippage_bps,
                        explanation_id, timestamp
                 FROM signals
                 ORDER BY timestamp DESC
                 LIMIT ?1",
            )
            .map_err(|e| e.to_string())?;

        let rows = stmt
            .query_map([limit], |row| {
                Ok(serde_json::json!({
                    "signal_id": row.get::<_, String>(0)?,
                    "job_id": row.get::<_, String>(1)?,
                    "symbol": row.get::<_, String>(2)?,
                    "direction": row.get::<_, String>(3)?,
                    "confidence": row.get::<_, f64>(4)?,
                    "target_quantity": row.get::<_, f64>(5)?,
                    "horizon_minutes": row.get::<_, i64>(6)?,
                    "exec_status": row.get::<_, Option<String>>(7)?,
                    "exec_latency_ms": row.get::<_, Option<i64>>(8)?,
                    "exec_filled_qty": row.get::<_, Option<f64>>(9)?,
                    "exec_slippage_bps": row.get::<_, Option<f64>>(10)?,
                    "explanation_id": row.get::<_, Option<String>>(11)?,
                    "timestamp": row.get::<_, String>(12)?,
                }))
            })
            .map_err(|e| e.to_string())?;

        let mut out = Vec::new();
        for row in rows {
            match row {
                Ok(v) => out.push(v),
                Err(e) => warn!("Row decode failed: {}", e),
            }
        }
        Ok(out)
    }
}

fn persist_signal(
    tx: &rusqlite::Transaction<'_>,
    job_id: &str,
    signal: &TradingSignal,
) -> Result<(), String> {
    let exec_status = signal.metadata.get("exec_status");
    let exec_latency_ms = signal
        .metadata
        .get("exec_latency_ms")
        .and_then(|v| v.parse::<i64>().ok());
    let exec_filled_qty = signal
        .metadata
        .get("exec_filled_qty")
        .and_then(|v| v.parse::<f64>().ok());
    let exec_slippage_bps = signal
        .metadata
        .get("exec_slippage_bps")
        .and_then(|v| v.parse::<f64>().ok());
    let explanation_id = signal.metadata.get("explanation_id");

    tx.execute(
        "INSERT OR REPLACE INTO signals (
            signal_id, job_id, symbol, direction, confidence,
            target_quantity, horizon_minutes, exec_status,
            exec_latency_ms, exec_filled_qty, exec_slippage_bps,
            explanation_id, timestamp
        ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13)",
        rusqlite::params![
            signal.signal_id,
            job_id,
            signal.symbol,
            signal.direction,
            signal.confidence,
            signal.target_quantity,
            signal.horizon_minutes,
            exec_status,
            exec_latency_ms,
            exec_filled_qty,
            exec_slippage_bps,
            explanation_id,
            signal.timestamp.to_rfc3339(),
        ],
    )
    .map_err(|e| e.to_string())
    .map(|_| ())
}

#[cfg(test)]
mod tests {
    use super::*;
    use super::super::types::*;
    use std::collections::HashMap;

    fn sample_result(job_suffix: &str) -> PipelineResult {
        let mut metadata = HashMap::new();
        metadata.insert("exec_status".to_string(), "Completed".to_string());
        metadata.insert("exec_latency_ms".to_string(), "3".to_string());
        metadata.insert("exec_filled_qty".to_string(), "10".to_string());
        metadata
            .insert("exec_slippage_bps".to_string(), "9.990009990009778".to_string());

        PipelineResult {
            job_id: format!("job-{}", job_suffix),
            status: JobStatus::Complete,
            phase: PipelinePhase::Complete,
            signals: vec![TradingSignal {
                signal_id: format!("sig-{}", job_suffix),
                timestamp: chrono::Utc::now(),
                symbol: "NG:CME".to_string(),
                direction: "Neutral".to_string(),
                confidence: 0.9998,
                target_quantity: 10.0,
                horizon_minutes: 60,
                metadata,
            }],
            metrics: PipelineMetrics::default(),
            error: None,
            execution_responses: vec![],
        }
    }

    #[test]
    fn persist_and_read_back() {
        let path = std::env::temp_dir().join(format!(
            "metis_persist_test_{}.sqlite",
            uuid::Uuid::new_v4()
        ));
        let store = Persistence::new(&path).unwrap();

        store.persist_result(&sample_result("a")).unwrap();

        let recent = store.recent_signals(10).unwrap();
        assert_eq!(recent.len(), 1);
        assert_eq!(recent[0]["signal_id"], "sig-a");
        assert_eq!(recent[0]["exec_status"], "Completed");
        assert_eq!(recent[0]["exec_latency_ms"], 3);
        assert_eq!(recent[0]["exec_filled_qty"], 10.0);
        assert!(
            (recent[0]["exec_slippage_bps"].as_f64().unwrap() - 9.990009990009778).abs() < 1e-12
        );

        // Re-persisting the same job must not duplicate its signals.
        store.persist_result(&sample_result("a")).unwrap();
        assert_eq!(store.recent_signals(10).unwrap().len(), 1);

        std::fs::remove_file(&path).ok();
    }

    #[test]
    fn empty_db_returns_empty() {
        let path = std::env::temp_dir().join(format!(
            "metis_persist_test_{}.sqlite",
            uuid::Uuid::new_v4()
        ));
        let store = Persistence::new(&path).unwrap();
        assert!(store.recent_signals(50).unwrap().is_empty());
        std::fs::remove_file(&path).ok();
    }
}
