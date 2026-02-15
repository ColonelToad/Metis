/// Background validation diagnostics for orchestrator service
/// Runs after app startup to ensure service health
/// Can be triggered with --validate flag
use std::time::Duration;
use tracing::{info, warn};

pub async fn run_background_diagnostics(port: u16) {
    info!("Starting background diagnostics (non-blocking)");

    tokio::spawn(async move {
        match run_diagnostics_internal(port).await {
            Ok(summary) => {
                info!("✓ Diagnostics passed: {}", summary);
            }
            Err(e) => {
                warn!("⚠ Diagnostics failed: {}", e);
            }
        }
    });
}

async fn run_diagnostics_internal(port: u16) -> Result<String, String> {
    // Give the service a moment to fully initialize
    tokio::time::sleep(Duration::from_millis(500)).await;

    let client = reqwest::Client::new();
    let base_url = format!("http://127.0.0.1:{}", port);

    // Health check
    let health_resp = client
        .get(format!("{}/api/health", base_url))
        .timeout(Duration::from_secs(5))
        .send()
        .await
        .map_err(|e| format!("Health check failed: {}", e))?;

    if health_resp.status() != 200 {
        return Err("Health check returned non-200 status".to_string());
    }

    let health_data: serde_json::Value = health_resp
        .json()
        .await
        .map_err(|e| format!("Failed to parse health response: {}", e))?;

    let uptime = health_data["uptime_seconds"].as_u64().unwrap_or(0);

    Ok(format!("Service healthy (uptime: {}s)", uptime))
}

/// Run a synchronous diagnostic check (for blocking startup validation)
pub fn run_synchronous_diagnostics(port: u16) -> Result<String, String> {
    let rt =
        tokio::runtime::Runtime::new().map_err(|e| format!("Failed to create runtime: {}", e))?;

    rt.block_on(async { run_diagnostics_internal(port).await })
}
