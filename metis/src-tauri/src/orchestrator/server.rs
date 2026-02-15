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
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;
use tower_http::cors::CorsLayer;
use tracing::{error, info, warn};
use types::*;

use crate::orchestrator::{error, job_queue, orchestrator, types};

pub struct AppState {
    orchestrator: Arc<Orchestrator>,
    job_queue: Arc<JobQueue>,
    start_time: Instant,
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

    let orchestrator = Arc::new(Orchestrator::new(project_root));
    let job_queue = Arc::new(JobQueue::new());

    let state = AppState {
        orchestrator,
        job_queue,
        start_time: Instant::now(),
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
        Ok(true) => {
            // Job is running, spawn it as background task
            let orchestrator = state.orchestrator.clone();
            let job_id_clone = job_id.clone();
            let mode = payload.mode.clone();

            info!(
                "[{}] Submitting pipeline execution (mode: {:?})",
                job_id_clone, mode
            );

            tokio::spawn(async move {
                match orchestrator
                    .run_pipeline(job_id_clone.clone(), mode.clone())
                    .await
                {
                    Ok(result) => {
                        info!("[{}] Pipeline completed successfully", job_id_clone);
                        info!(
                            "[{}] Generated {} signals",
                            job_id_clone,
                            result.signals.len()
                        );
                    }
                    Err(e) => {
                        error!("[{}] Pipeline failed: {}", job_id_clone, e);
                    }
                }
            });

            Ok((
                StatusCode::ACCEPTED,
                Json(RunPipelineResponse {
                    job_id: job_id.clone(),
                    status: JobStatus::Running,
                    phase: PipelinePhase::Ingestion,
                }),
            ))
        }
        Ok(false) => {
            // Job is queued
            warn!(
                "[{}] Pipeline queued (another execution in progress)",
                job_id
            );
            Ok((
                StatusCode::ACCEPTED,
                Json(RunPipelineResponse {
                    job_id: job_id.clone(),
                    status: JobStatus::Queued,
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
