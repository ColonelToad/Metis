use super::error::OrchestrationError;
use super::python_runner::{PythonPipelineResult, PythonRunner};
use super::types::*;
use chrono::DateTime;
use parking_lot::RwLock;
use rag::ExplainabilityRAG;
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;
use tracing::{error, info, warn};

/// Main orchestrator for managing pipeline execution
pub struct Orchestrator {
    python_runner: PythonRunner,
    results: Arc<RwLock<HashMap<String, PipelineResult>>>,
    project_root: PathBuf,
    rag_pipeline: Option<Arc<ExplainabilityRAG>>,
}

impl Orchestrator {
    pub async fn new(project_root: PathBuf) -> Self {
        let python_runner = PythonRunner::new(project_root.clone());

        // Initialize RAG pipeline (optional - log failures but don't fail the whole orchestrator)
        let rag_pipeline = Self::init_rag_pipeline(&project_root).await;
        if rag_pipeline.is_none() {
            warn!("RAG pipeline initialization failed - explanations will not be generated");
        }

        Self {
            python_runner,
            results: Arc::new(RwLock::new(HashMap::new())),
            project_root,
            rag_pipeline,
        }
    }

    /// Initialize the RAG pipeline
    async fn init_rag_pipeline(project_root: &PathBuf) -> Option<Arc<ExplainabilityRAG>> {
        let model_path = project_root.join("rag/llm/DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf");
        let db_path = project_root.join("rag/lancedb");

        match ExplainabilityRAG::new(
            model_path.to_string_lossy().as_ref(),
            db_path.to_string_lossy().as_ref(),
            false, // not mock mode in production
        )
        .await
        {
            Ok(rag) => {
                info!("RAG pipeline initialized successfully");
                Some(Arc::new(rag))
            }
            Err(e) => {
                warn!("Failed to initialize RAG pipeline: {}", e);
                None
            }
        }
    }

    /// Run a complete pipeline
    pub async fn run_pipeline(
        &self,
        job_id: String,
        mode: ExecutionMode,
    ) -> Result<PipelineResult, OrchestrationError> {
        let start = Instant::now();
        let mode_str = mode.to_string();

        info!("[{}] Pipeline started (mode: {})", job_id, mode_str);
        info!("[{}] Setting METIS_MODE={}", job_id, &mode_str);

        // Set environment variable for Python
        std::env::set_var("METIS_MODE", &mode_str);

        // Run Python pipeline
        match self.python_runner.run_pipeline().await {
            Ok(python_result) => self.handle_success(&job_id, python_result, mode, start).await,
            Err(e) => {
                let error_msg = format!("Python pipeline execution failed: {}", e);
                error!("[{}] {}", job_id, error_msg);

                let result = PipelineResult {
                    job_id: job_id.clone(),
                    status: JobStatus::Error,
                    phase: PipelinePhase::Error,
                    error: Some(error_msg),
                    ..Default::default()
                };

                // Store result
                {
                    let mut results = self.results.write();
                    results.insert(job_id, result.clone());
                }

                Err(OrchestrationError::InternalError(
                    "Pipeline failed".to_string(),
                ))
            }
        }
    }

    /// Handle successful Python execution
    async fn handle_success(
        &self,
        job_id: &str,
        python_result: PythonPipelineResult,
        mode: ExecutionMode,
        start: Instant,
    ) -> Result<PipelineResult, OrchestrationError> {
        info!(
            "[{}] Python pipeline returned: status={}",
            job_id, python_result.status
        );

        // Parse metrics from Python output
        let metrics_json = &python_result.metrics;

        let total_time = metrics_json["total_time"]
            .as_f64()
            .unwrap_or(start.elapsed().as_secs_f64());

        let ingest_time = metrics_json["ingest_time"].as_f64().unwrap_or(0.0);
        let feature_time = metrics_json["feature_time"].as_f64().unwrap_or(0.0);
        let inference_time = metrics_json["inference_time"].as_f64().unwrap_or(0.0);
        let signals_generated = metrics_json["signals_generated"].as_u64().unwrap_or(0) as u32;
        let avg_confidence = metrics_json["avg_confidence"].as_f64().unwrap_or(0.0);

        let ingest_success = metrics_json["ingest_success"].as_bool().unwrap_or(false);
        let features_success = metrics_json["features_success"].as_bool().unwrap_or(false);
        let inference_success = metrics_json["inference_success"].as_bool().unwrap_or(false);

        info!(
            "[{}] Metrics: total={:.2}s, ingest={:.2}s, features={:.2}s, inference={:.2}s",
            job_id, total_time, ingest_time, feature_time, inference_time
        );
        info!(
            "[{}] Phases: ingest={}, features={}, inference={}",
            job_id, ingest_success, features_success, inference_success
        );

        // Parse signals from Python output and generate explanations
        let mut signals = Vec::new();
        for signal_json in python_result.signals {
            if let Ok(signal) = self.parse_signal(&signal_json) {
                info!(
                    "[{}] Parsed signal: {} {} @{:.2}",
                    job_id, signal.symbol, signal.direction, signal.confidence
                );

                // Generate explanation if RAG pipeline is available
                if let Some(rag) = &self.rag_pipeline {
                    let rag_signal = Self::signal_to_rag(&signal);
                    let explain_start = Instant::now();

                    match rag.explain_signal(&rag_signal).await {
                        rag::pipeline::ExplanationResult::Success { explanation } => {
                            let explain_duration = explain_start.elapsed();
                            info!(
                                "[{}] Generated explanation for signal {} in {:.2}s",
                                job_id,
                                signal.signal_id,
                                explain_duration.as_secs_f64()
                            );
                            // Store explanation in metadata for later retrieval
                            let mut signal_with_explanation = signal.clone();
                            signal_with_explanation.metadata.insert(
                                "explanation_id".to_string(),
                                explanation.signal_id.clone(),
                            );
                            signals.push(signal_with_explanation);
                        }
                        _ => {
                            warn!(
                                "[{}] Failed to generate explanation for signal {}",
                                job_id, signal.signal_id
                            );
                            signals.push(signal);
                        }
                    }
                } else {
                    signals.push(signal);
                }
            } else {
                warn!("[{}] Failed to parse signal: {:?}", job_id, signal_json);
            }
        }

        // Log any errors from Python execution
        if !python_result.errors.is_empty() {
            warn!(
                "[{}] Python execution had {} errors:",
                job_id,
                python_result.errors.len()
            );
            for err in &python_result.errors {
                warn!("[{}]   - {}", job_id, err);
            }
        }

        // Build metrics
        let metrics = PipelineMetrics {
            total_time,
            ingest_time,
            feature_time,
            inference_time,
            signal_collection_time: 0.1, // Phase 4: signal collection (minimal overhead)
            lmp_cache_hit: ingest_time < 0.5, // Fast phase suggests cache
            cme_cache_hit: ingest_time < 0.5,
            signals_generated,
            avg_confidence,
            run_timestamp: chrono::Utc::now(),
            mode,
        };

        // Determine overall status
        let status = if python_result.status == "complete"
            && ingest_success
            && features_success
            && inference_success
        {
            JobStatus::Complete
        } else if signals.is_empty() && !python_result.errors.is_empty() {
            JobStatus::Error
        } else {
            JobStatus::Partial
        };

        let error = if !python_result.errors.is_empty() {
            Some(format!(
                "Pipeline had {} error(s). Check logs for details.",
                python_result.errors.len()
            ))
        } else {
            None
        };

        let result = PipelineResult {
            job_id: job_id.to_string(),
            status: status.clone(),
            phase: PipelinePhase::Complete,
            signals,
            metrics,
            error,
            execution_responses: vec![],
        };

        info!(
            "[{}] Pipeline completed in {:.2}s (status: {})",
            job_id, total_time, status
        );

        // Store result
        {
            let mut results = self.results.write();
            results.insert(job_id.to_string(), result.clone());
        }

        Ok(result)
    }

    /// Convert orchestrator signal to RAG signal format
    fn signal_to_rag(orch_signal: &TradingSignal) -> rag::types::TradingSignal {
        // Extract context from metadata if available
        let grid_stress = orch_signal
            .metadata
            .get("grid_stress_index")
            .and_then(|v| v.parse::<f64>().ok())
            .unwrap_or(50.0);

        let temp_anomaly = orch_signal
            .metadata
            .get("temperature_anomaly")
            .and_then(|v| v.parse::<f64>().ok())
            .unwrap_or(0.0);

        let primary_region = orch_signal
            .metadata
            .get("primary_region")
            .cloned()
            .unwrap_or_else(|| "ERCOT".to_string());

        let recent_policy = orch_signal
            .metadata
            .get("policy_events")
            .map(|s| s.split(';').map(|e| e.to_string()).collect())
            .unwrap_or_default();

        rag::types::TradingSignal {
            id: orch_signal.signal_id.clone(),
            instrument: orch_signal.symbol.clone(),
            direction: match orch_signal.direction.to_uppercase().as_str() {
                "BUY" => "LONG".to_string(),
                "SELL" => "SHORT".to_string(),
                other => other.to_string(),
            },
            confidence: orch_signal.confidence,
            timestamp: orch_signal.timestamp,
            context: rag::types::TradingContext {
                current_price: orch_signal
                    .metadata
                    .get("current_price")
                    .and_then(|v| v.parse::<f64>().ok())
                    .unwrap_or(0.0),
                grid_stress_index: grid_stress,
                temperature_anomaly: temp_anomaly,
                recent_policy_events: recent_policy,
                primary_region,
            },
        }
    }

    /// Parse a signal from JSON
    fn parse_signal(&self, signal_json: &serde_json::Value) -> Result<TradingSignal, String> {
        let signal_id = signal_json["signal_id"]
            .as_str()
            .ok_or("Missing signal_id")?
            .to_string();

        let timestamp_str = signal_json["timestamp"]
            .as_str()
            .ok_or("Missing timestamp")?;

        let timestamp = DateTime::parse_from_rfc3339(timestamp_str)
            .map_err(|e| format!("Invalid timestamp: {}", e))?
            .with_timezone(&chrono::Utc);

        let symbol = signal_json["symbol"]
            .as_str()
            .ok_or("Missing symbol")?
            .to_string();

        let direction = signal_json["direction"]
            .as_str()
            .ok_or("Missing direction")?
            .to_string();

        let confidence = signal_json["confidence"]
            .as_f64()
            .ok_or("Missing confidence")?;

        let target_quantity = signal_json["target_quantity"]
            .as_f64()
            .ok_or("Missing target_quantity")?;

        let horizon_minutes = signal_json["horizon_minutes"]
            .as_i64()
            .ok_or("Missing horizon_minutes")?;

        let metadata = signal_json["metadata"]
            .as_object()
            .map(|m| {
                m.iter()
                    .map(|(k, v)| (k.clone(), v.as_str().unwrap_or("").to_string()))
                    .collect()
            })
            .unwrap_or_default();

        Ok(TradingSignal {
            signal_id,
            timestamp,
            symbol,
            direction,
            confidence,
            target_quantity,
            horizon_minutes,
            metadata,
        })
    }

    /// Get pipeline result by job ID
    pub fn get_result(&self, job_id: &str) -> Option<PipelineResult> {
        self.results.read().get(job_id).cloned()
    }

    /// Get pipeline status by job ID
    pub fn get_status(&self, job_id: &str) -> Option<StatusResponse> {
        let results = self.results.read();
        results.get(job_id).map(|result| StatusResponse {
            job_id: result.job_id.clone(),
            status: result.status.clone(),
            phase: result.phase.clone(),
            progress: match result.status {
                JobStatus::Running => 50,
                JobStatus::Complete => 100,
                JobStatus::Partial => 75,
                JobStatus::Error => 0,
                _ => 0,
            },
            timing: super::types::PhaseTiming {
                ingest_time: result.metrics.ingest_time,
                feature_time: result.metrics.feature_time,
                inference_time: result.metrics.inference_time,
                signal_collection_time: result.metrics.signal_collection_time,
                total_time: result.metrics.total_time,
            },
            cache_hits: {
                let mut hits = HashMap::new();
                hits.insert("lmp".to_string(), result.metrics.lmp_cache_hit);
                hits.insert("cme".to_string(), result.metrics.cme_cache_hit);
                hits
            },
            error: result.error.clone(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_orchestrator_new() {
        let root = PathBuf::from("/tmp");
        let orch = Orchestrator::new(root.clone()).await;
        assert_eq!(orch.project_root, root);
    }
}
