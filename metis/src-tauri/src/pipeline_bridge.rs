/// HTTP client bridge to communicate with orchestrator service
/// Provides Tauri commands that call the local orchestrator on :9000

use reqwest::Client;
use serde_json::json;
use tracing::{error, info};

const ORCHESTRATOR_URL: &str = "http://127.0.0.1:9000";

/// Start a new pipeline execution
pub async fn run_pipeline(mode: String, force_refresh: bool) -> Result<serde_json::Value, String> {
    let client = Client::new();
    let url = format!("{}/api/pipeline/run", ORCHESTRATOR_URL);

    let payload = json!({
        "mode": mode.to_uppercase(),
        "force_refresh": force_refresh
    });

    info!("Running pipeline with mode: {}", mode);

    match client.post(&url).json(&payload).send().await {
        Ok(response) => {
            match response.json::<serde_json::Value>().await {
                Ok(data) => {
                    info!("Pipeline started: {:?}", data);
                    Ok(data)
                }
                Err(e) => {
                    error!("Failed to parse pipeline response: {}", e);
                    Err(format!("Failed to parse response: {}", e))
                }
            }
        }
        Err(e) => {
            error!("Failed to call orchestrator: {}", e);
            Err(format!("Failed to reach orchestrator: {}", e))
        }
    }
}

/// Get pipeline execution status
pub async fn get_pipeline_status(job_id: String) -> Result<serde_json::Value, String> {
    let client = Client::new();
    let url = format!("{}/api/pipeline/status/{}", ORCHESTRATOR_URL, job_id);

    info!("Fetching pipeline status for job: {}", job_id);

    match client.get(&url).send().await {
        Ok(response) => {
            match response.json::<serde_json::Value>().await {
                Ok(data) => Ok(data),
                Err(e) => {
                    error!("Failed to parse status response: {}", e);
                    Err(format!("Failed to parse response: {}", e))
                }
            }
        }
        Err(e) => {
            error!("Failed to fetch status: {}", e);
            Err(format!("Failed to reach orchestrator: {}", e))
        }
    }
}

/// Get pipeline results
pub async fn get_pipeline_results(job_id: String) -> Result<serde_json::Value, String> {
    let client = Client::new();
    let url = format!("{}/api/pipeline/results/{}", ORCHESTRATOR_URL, job_id);

    info!("Fetching pipeline results for job: {}", job_id);

    match client.get(&url).send().await {
        Ok(response) => {
            match response.json::<serde_json::Value>().await {
                Ok(data) => Ok(data),
                Err(e) => {
                    error!("Failed to parse results response: {}", e);
                    Err(format!("Failed to parse response: {}", e))
                }
            }
        }
        Err(e) => {
            error!("Failed to fetch results: {}", e);
            Err(format!("Failed to reach orchestrator: {}", e))
        }
    }
}

/// Health check
pub async fn health_check() -> Result<serde_json::Value, String> {
    let client = Client::new();
    let url = format!("{}/api/health", ORCHESTRATOR_URL);

    match client.get(&url).send().await {
        Ok(response) => {
            match response.json::<serde_json::Value>().await {
                Ok(data) => Ok(data),
                Err(e) => {
                    error!("Failed to parse health response: {}", e);
                    Err(format!("Failed to parse response: {}", e))
                }
            }
        }
        Err(e) => {
            error!("Orchestrator health check failed: {}", e);
            Err(format!("Orchestrator unavailable: {}", e))
        }
    }
}
