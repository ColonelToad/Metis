use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use uuid::Uuid;

/// Unique job ID for tracking pipeline runs
#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize, PartialOrd, Ord)]
pub struct JobId(pub String);

impl JobId {
    pub fn new() -> Self {
        Self(Uuid::new_v4().to_string())
    }
}

impl Default for JobId {
    fn default() -> Self {
        Self::new()
    }
}

/// Current execution phase of the pipeline
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum PipelinePhase {
    Ingestion,
    Features,
    Inference,
    SignalCollection,
    Complete,
    Error,
}

impl std::fmt::Display for PipelinePhase {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Ingestion => write!(f, "ingestion"),
            Self::Features => write!(f, "features"),
            Self::Inference => write!(f, "inference"),
            Self::SignalCollection => write!(f, "signal_collection"),
            Self::Complete => write!(f, "complete"),
            Self::Error => write!(f, "error"),
        }
    }
}

/// Pipeline execution mode
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "UPPERCASE")]
pub enum ExecutionMode {
    Dev,
    Real,
}

impl std::fmt::Display for ExecutionMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Dev => write!(f, "DEV"),
            Self::Real => write!(f, "REAL"),
        }
    }
}

/// Current status of a job
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum JobStatus {
    Running,
    Queued,
    Complete,
    Error,
    Partial,
}

impl std::fmt::Display for JobStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Running => write!(f, "running"),
            Self::Queued => write!(f, "queued"),
            Self::Complete => write!(f, "complete"),
            Self::Error => write!(f, "error"),
            Self::Partial => write!(f, "partial"),
        }
    }
}

/// Timing information for each phase
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PhaseTiming {
    pub ingest_time: f64,
    pub feature_time: f64,
    pub inference_time: f64,
    pub signal_collection_time: f64,
    pub total_time: f64,
}

impl Default for PhaseTiming {
    fn default() -> Self {
        Self {
            ingest_time: 0.0,
            feature_time: 0.0,
            inference_time: 0.0,
            signal_collection_time: 0.0,
            total_time: 0.0,
        }
    }
}

/// Performance metrics for the pipeline run
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PipelineMetrics {
    pub total_time: f64,
    pub ingest_time: f64,
    pub feature_time: f64,
    pub inference_time: f64,
    pub signal_collection_time: f64,
    pub lmp_cache_hit: bool,
    pub cme_cache_hit: bool,
    pub signals_generated: u32,
    pub avg_confidence: f64,
    pub run_timestamp: DateTime<Utc>,
    pub mode: ExecutionMode,
}

impl Default for PipelineMetrics {
    fn default() -> Self {
        Self {
            total_time: 0.0,
            ingest_time: 0.0,
            feature_time: 0.0,
            inference_time: 0.0,
            signal_collection_time: 0.0,
            lmp_cache_hit: false,
            cme_cache_hit: false,
            signals_generated: 0,
            avg_confidence: 0.0,
            run_timestamp: Utc::now(),
            mode: ExecutionMode::Dev,
        }
    }
}

/// A single trading signal
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TradingSignal {
    pub signal_id: String,
    pub timestamp: DateTime<Utc>,
    pub symbol: String,
    pub direction: String,
    pub confidence: f64,
    pub target_quantity: f64,
    pub horizon_minutes: i64,
    pub metadata: HashMap<String, String>,
}

/// Response from a pipeline execution
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PipelineResult {
    pub job_id: String,
    pub status: JobStatus,
    pub phase: PipelinePhase,
    pub signals: Vec<TradingSignal>,
    pub metrics: PipelineMetrics,
    pub error: Option<String>,
    pub execution_responses: Vec<serde_json::Value>,
}

impl Default for PipelineResult {
    fn default() -> Self {
        Self {
            job_id: JobId::new().0,
            status: JobStatus::Running,
            phase: PipelinePhase::Ingestion,
            signals: vec![],
            metrics: PipelineMetrics::default(),
            error: None,
            execution_responses: vec![],
        }
    }
}

/// Request to start a pipeline
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RunPipelineRequest {
    pub mode: ExecutionMode,
    #[serde(default)]
    pub force_refresh: bool,
}

/// Response when pipeline is started
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RunPipelineResponse {
    pub job_id: String,
    pub status: JobStatus,
    pub phase: PipelinePhase,
}

/// Status response during pipeline execution
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StatusResponse {
    pub job_id: String,
    pub status: JobStatus,
    pub phase: PipelinePhase,
    pub progress: u32,
    pub timing: PhaseTiming,
    pub cache_hits: HashMap<String, bool>,
    pub error: Option<String>,
}

/// Health check response
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HealthResponse {
    pub status: String,
    pub uptime_seconds: u64,
    pub version: String,
}
