"""
Metis Metrics Collection
Centralizes profiling/performance data into SQLite for trending and analysis

Usage:
    collector = MetricsCollector()
    run_id = collector.start_run(environment="DEV")
    
    # During run, batch metrics in memory
    collector.add_metric("pipeline_total_ms", 1234.5)
    collector.add_metric("ingest_time_ms", 567.8)
    collector.add_ingester_result("EIA", "success", 234.5, 1500)
    
    # At end, write all to SQLite
    collector.finalize_run(status="success")
"""

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict


@dataclass
class IngesterResult:
    """Result of a single ingester run"""
    ingester_name: str
    status: str  # success, failed, skipped
    duration_ms: float
    row_count: int
    error_msg: Optional[str] = None


class MetricsCollector:
    """Batch metrics in memory, write to SQLite at end of run"""
    
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = Path(__file__).parent / "logs" / "metrics.db"
        
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize DB if needed
        self._init_db()
        
        # Batch storage (write at end)
        self.run_id: Optional[str] = None
        self.start_time: Optional[datetime] = None
        self.environment: str = "DEV"
        self.metrics: Dict[str, float] = {}  # metric_name -> value
        self.ingester_results: Dict[str, IngesterResult] = {}  # ingester_name -> result
        self.tags: Dict[str, Any] = {}  # Extra context (git_commit, notes, etc.)
    
    def _init_db(self):
        """Create tables if they don't exist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Runs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                start_time DATETIME NOT NULL,
                end_time DATETIME,
                environment TEXT NOT NULL,
                status TEXT,
                notes TEXT,
                git_commit TEXT
            )
        """)
        
        # Metrics table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                value REAL NOT NULL,
                unit TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            )
        """)
        
        # Ingester results table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ingester_results (
                result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                ingester_name TEXT NOT NULL,
                status TEXT NOT NULL,
                duration_ms REAL NOT NULL,
                row_count INTEGER,
                error_msg TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            )
        """)
        
        conn.commit()
        conn.close()
    
    def start_run(self, environment: str = "DEV", git_commit: str = None) -> str:
        """Start a new metrics collection run. Returns run_id."""
        self.run_id = f"run_{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.start_time = datetime.now()
        self.environment = environment
        self.metrics = {}
        self.ingester_results = {}
        self.tags = {"git_commit": git_commit} if git_commit else {}
        
        return self.run_id
    
    def add_metric(self, name: str, value: float, unit: str = ""):
        """Add a metric to the batch. Overwrites if duplicate."""
        if not self.run_id:
            raise RuntimeError("Call start_run() first")
        self.metrics[name] = value
    
    def add_ingester_result(
        self,
        ingester_name: str,
        status: str,
        duration_ms: float,
        row_count: int,
        error_msg: str = None
    ):
        """Add ingester result to batch"""
        if not self.run_id:
            raise RuntimeError("Call start_run() first")
        
        self.ingester_results[ingester_name] = IngesterResult(
            ingester_name=ingester_name,
            status=status,
            duration_ms=duration_ms,
            row_count=row_count,
            error_msg=error_msg
        )
    
    def add_tag(self, key: str, value: Any):
        """Add metadata tag (e.g., git_commit, notes)"""
        self.tags[key] = value
    
    def finalize_run(self, status: str = "success", notes: str = None) -> str:
        """Write all batched metrics to SQLite. Returns run_id."""
        if not self.run_id:
            raise RuntimeError("Call start_run() first")
        
        end_time = datetime.now()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Insert run record
            cursor.execute("""
                INSERT INTO runs (run_id, start_time, end_time, environment, status, notes, git_commit)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                self.run_id,
                self.start_time,
                end_time,
                self.environment,
                status,
                notes,
                self.tags.get("git_commit")
            ))
            
            # Insert metrics
            for metric_name, value in self.metrics.items():
                unit = ""
                if metric_name.endswith("_ms"):
                    unit = "ms"
                elif metric_name.endswith("_ns"):
                    unit = "ns"
                elif metric_name.endswith("_count"):
                    unit = "count"
                elif metric_name.endswith("_pct"):
                    unit = "%"
                
                cursor.execute("""
                    INSERT INTO metrics (run_id, metric_name, value, unit)
                    VALUES (?, ?, ?, ?)
                """, (self.run_id, metric_name, value, unit))
            
            # Insert ingester results
            for ingester_result in self.ingester_results.values():
                cursor.execute("""
                    INSERT INTO ingester_results (run_id, ingester_name, status, duration_ms, row_count, error_msg)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    self.run_id,
                    ingester_result.ingester_name,
                    ingester_result.status,
                    ingester_result.duration_ms,
                    ingester_result.row_count,
                    ingester_result.error_msg
                ))
            
            conn.commit()
        finally:
            conn.close()
        
        return self.run_id
    
    # ==================== QUERY METHODS ====================
    
    def get_recent_runs(self, limit: int = 10) -> list:
        """Get last N runs with basic info"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT run_id, start_time, environment, status
            FROM runs
            ORDER BY start_time DESC
            LIMIT ?
        """, (limit,))
        
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results
    
    def get_run_metrics(self, run_id: str) -> Dict[str, float]:
        """Get all metrics for a specific run"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT metric_name, value
            FROM metrics
            WHERE run_id = ?
        """, (run_id,))
        
        metrics = {row['metric_name']: row['value'] for row in cursor.fetchall()}
        conn.close()
        return metrics
    
    def get_run_ingesters(self, run_id: str) -> list:
        """Get all ingester results for a specific run"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT ingester_name, status, duration_ms, row_count, error_msg
            FROM ingester_results
            WHERE run_id = ?
            ORDER BY ingester_name
        """, (run_id,))
        
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results
    
    def get_metric_trend(self, metric_name: str, days: int = 7) -> list:
        """Get metric values over last N days"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT r.start_time, m.value
            FROM metrics m
            JOIN runs r ON m.run_id = r.run_id
            WHERE m.metric_name = ? AND r.start_time > datetime('now', '-' || ? || ' days')
            ORDER BY r.start_time
        """, (metric_name, days))
        
        results = [{"timestamp": row['start_time'], "value": row['value']} for row in cursor.fetchall()]
        conn.close()
        return results
    
    def get_ingester_health(self, days: int = 7) -> Dict[str, Dict]:
        """Get success rate per ingester over last N days"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                ingester_name,
                COUNT(*) as total_runs,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful_runs,
                AVG(CASE WHEN status = 'success' THEN duration_ms ELSE NULL END) as avg_duration_ms
            FROM ingester_results
            WHERE run_id IN (
                SELECT run_id FROM runs WHERE start_time > datetime('now', '-' || ? || ' days')
            )
            GROUP BY ingester_name
            ORDER BY ingester_name
        """, (days,))
        
        health = {}
        for row in cursor.fetchall():
            health[row['ingester_name']] = {
                "total": row['total_runs'],
                "successful": row['successful_runs'],
                "success_rate": row['successful_runs'] / row['total_runs'] if row['total_runs'] > 0 else 0,
                "avg_duration_ms": row['avg_duration_ms']
            }
        
        conn.close()
        return health
    
    def query(self, sql: str, params: tuple = ()) -> list:
        """Raw SQL query for ad-hoc analysis"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute(sql, params)
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results
