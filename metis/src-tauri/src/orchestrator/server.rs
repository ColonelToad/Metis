/// HTTP server for orchestrator service
/// Runs as a background task within the Tauri app
use axum::{
    extract::{Path, State},
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use job_queue::JobQueue;
use orchestrator::Orchestrator;
use parking_lot::RwLock;
use std::collections::HashMap;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;
use tower_http::cors::CorsLayer;
use tracing::{error, info, warn};
use types::*;

use crate::orchestrator::{engines, error, job_queue, orchestrator, types};

pub struct AppState {
    orchestrator: Arc<Orchestrator>,
    job_queue: Arc<JobQueue>,
    start_time: Instant,
    /// Repo root, used to locate the Rust engine binary for /api/engines/start.
    project_root: PathBuf,
    /// Mode each submitted job was requested with, so a queued job can be
    /// started when its turn comes (JobQueue only tracks ids).
    job_modes: Arc<RwLock<HashMap<String, ExecutionMode>>>,
}

/// Start the orchestrator HTTP server
/// Runs on localhost with specified port (default 9000)
pub async fn start_http_server(project_root: PathBuf, port: u16) {
    // Initialize tracing
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("info".parse().unwrap()),
        )
        .init();

    info!("Project root: {}", project_root.display());

    let orchestrator = Arc::new(Orchestrator::new(project_root.clone()).await);
    let job_queue = Arc::new(JobQueue::new());

    let state = AppState {
        orchestrator,
        job_queue,
        start_time: Instant::now(),
        project_root: project_root.clone(),
        job_modes: Arc::new(RwLock::new(HashMap::new())),
    };

    let state = Arc::new(state);

    // Build router
    let app = Router::new()
        .route("/api/health", get(health_handler))
        .route("/api/pipeline/run", post(run_pipeline_handler))
        .route("/api/pipeline/status/:job_id", get(pipeline_status_handler))
        .route(
            "/api/pipeline/results/:job_id",
            get(pipeline_results_handler),
        )
        .route("/api/signals/recent", get(recent_signals_handler))
        .route("/api/engines/status", get(engines_status_handler))
        .route("/api/engines/start", post(start_engine_handler))
        .layer(CorsLayer::permissive())
        .with_state(state);

    // Start server
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let listener = tokio::net::TcpListener::bind(&addr)
        .await
        .unwrap_or_else(|_| panic!("Failed to bind to port {}", port));

    info!("🚀 Orchestrator service listening on http://{}", addr);

    axum::serve(listener, app).await.expect("Server crashed");
}

async fn health_handler(State(state): State<Arc<AppState>>) -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok".to_string(),
        uptime_seconds: state.start_time.elapsed().as_secs(),
        version: env!("CARGO_PKG_VERSION").to_string(),
    })
}

async fn run_pipeline_handler(
    State(state): State<Arc<AppState>>,
    Json(payload): Json<RunPipelineRequest>,
) -> Result<(StatusCode, Json<RunPipelineResponse>), error::OrchestrationError> {
    let job_id = JobId::new().0;

    info!("Pipeline run request received: mode={:?}", payload.mode);

    // Try to submit to queue
    match state.job_queue.submit(JobId(job_id.clone())) {
        Ok(started) => {
            state
                .job_modes
                .write()
                .insert(job_id.clone(), payload.mode.clone());

            if started {
                spawn_pipeline(state.clone(), job_id.clone());
            } else {
                warn!(
                    "[{}] Pipeline queued (another execution in progress)",
                    job_id
                );
            }

            Ok((
                StatusCode::ACCEPTED,
                Json(RunPipelineResponse {
                    job_id: job_id.clone(),
                    status: if started {
                        JobStatus::Running
                    } else {
                        JobStatus::Queued
                    },
                    phase: PipelinePhase::Ingestion,
                }),
            ))
        }
        Err(_msg) => {
            error!("[{}] Pipeline rejected - max queue depth exceeded", job_id);
            Err(error::OrchestrationError::JobAlreadyRunning)
        }
    }
}

/// Spawn a pipeline run and free its queue slot (promoting any queued job)
/// when it finishes.
fn spawn_pipeline(state: Arc<AppState>, job_id: String) {
    let orchestrator = Arc::clone(&state.orchestrator);
    let mode = state
        .job_modes
        .read()
        .get(&job_id)
        .cloned()
        .unwrap_or(ExecutionMode::Dev);

    info!(
        "[{}] Submitting pipeline execution (mode: {:?})",
        job_id, mode
    );

    tokio::spawn(async move {
        match orchestrator.run_pipeline(job_id.clone(), mode).await {
            Ok(result) => {
                info!("[{}] Pipeline completed successfully", job_id);
                info!(
                    "[{}] Generated {} signals",
                    job_id,
                    result.signals.len()
                );
            }
            Err(e) => {
                error!("[{}] Pipeline failed: {}", job_id, e);
            }
        }

        // Free the slot; start the promoted job if one was waiting.
        let promoted = state.job_queue.complete_current();
        state.job_modes.write().remove(&job_id);
        if let Some(next_id) = promoted {
            info!("[{}] Starting previously queued job {}", job_id, next_id.0);
            spawn_pipeline(Arc::clone(&state), next_id.0);
        }
    });
}

async fn engines_status_handler() -> Json<engines::EnginesStatusResponse> {
    Json(engines::engines_status().await)
}

#[derive(serde::Deserialize)]
struct StartEngineRequest {
    engine: String,
}

async fn start_engine_handler(
    State(state): State<Arc<AppState>>,
    Json(payload): Json<StartEngineRequest>,
) -> Result<Json<engines::StartEngineResponse>, (StatusCode, Json<serde_json::Value>)> {
    info!("Engine start request: {}", payload.engine);
    match engines::start_engine(&payload.engine, &state.project_root).await {
        Ok(resp) => {
            if resp.spawn_attempted {
                info!("Engine {} start result: {}", resp.engine, resp.detail);
            }
            Ok(Json(resp))
        }
        Err(e) => {
            error!("Engine {} failed to start: {}", payload.engine, e);
            Err((
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({ "error": e })),
            ))
        }
    }
}

async fn recent_signals_handler(
    State(state): State<Arc<AppState>>,
    axum::extract::Query(params): axum::extract::Query<HashMap<String, String>>,
) -> Json<serde_json::Value> {
    let limit = params
        .get("limit")
        .and_then(|v| v.parse::<u32>().ok())
        .unwrap_or(50)
        .min(500);
    match state.orchestrator.recent_signals(limit) {
        Ok(signals) => Json(serde_json::json!({ "signals": signals, "count": signals.len() })),
        Err(e) => {
            error!("Recent signals query failed: {}", e);
            Json(serde_json::json!({ "signals": [], "count": 0, "error": e }))
        }
    }
}

async fn pipeline_status_handler(
    State(state): State<Arc<AppState>>,
    Path(job_id): Path<String>,
) -> Result<Json<StatusResponse>, error::OrchestrationError> {
    match state.orchestrator.get_status(&job_id) {
        Some(status) => {
            info!(
                "[{}] Status requested: phase={}, progress={}%",
                job_id, status.phase, status.progress
            );
            Ok(Json(status))
        }
        None => {
            warn!("[{}] Status requested but job not found", job_id);
            Err(error::OrchestrationError::JobNotFound(job_id))
        }
    }
}

async fn pipeline_results_handler(
    State(state): State<Arc<AppState>>,
    Path(job_id): Path<String>,
) -> Result<Json<PipelineResult>, error::OrchestrationError> {
    match state.orchestrator.get_result(&job_id) {
        Some(result) => {
            info!(
                "[{}] Results requested: status={}, signals={}",
                job_id,
                result.status,
                result.signals.len()
            );
            Ok(Json(result))
        }
        None => {
            warn!("[{}] Results requested but job not found", job_id);
            Err(error::OrchestrationError::JobNotFound(job_id))
        }
    }
}
