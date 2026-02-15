// Learn more about Tauri commands at https://tauri.app/develop/calling-rust/
pub mod orchestrator;
mod pipeline_bridge;

use pipeline_bridge::{get_pipeline_results, get_pipeline_status, health_check, run_pipeline};
use pyo3::prepare_freethreaded_python;
use std::path::PathBuf;

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

/// Start a pipeline execution via orchestrator service
#[tauri::command]
async fn invoke_pipeline(
    mode: String,
    force_refresh: Option<bool>,
) -> Result<serde_json::Value, String> {
    run_pipeline(mode, force_refresh.unwrap_or(false)).await
}

/// Poll pipeline status
#[tauri::command]
async fn poll_pipeline_status(job_id: String) -> Result<serde_json::Value, String> {
    get_pipeline_status(job_id).await
}

/// Get pipeline results
#[tauri::command]
async fn fetch_pipeline_results(job_id: String) -> Result<serde_json::Value, String> {
    get_pipeline_results(job_id).await
}

/// Check if orchestrator service is running
#[tauri::command]
async fn check_orchestrator_health() -> Result<serde_json::Value, String> {
    health_check().await
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run_tauri() {
    // Initialize Python interpreter for multi-threaded use
    // This must be done ONCE before any Python APIs are called from any thread
    prepare_freethreaded_python();

    // Check for --validate flag (background diagnostics mode)
    let validate_mode = std::env::args().any(|arg| arg == "--validate");

    // Start orchestrator service in background thread with its own tokio runtime
    let _orchestrator_handle = std::thread::spawn(move || {
        // Calculate the actual project root
        // CARGO_MANIFEST_DIR is the directory of the Cargo.toml being compiled (metis/src-tauri)
        // We need to go up 2 levels to reach the project root where research/ folder is
        let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|p| p.parent())
            .map(|p| p.to_path_buf())
            .unwrap_or_else(|| PathBuf::from("."));

        tracing::info!("Project root resolved to: {}", project_root.display());

        let rt = tokio::runtime::Runtime::new().expect("Failed to create tokio runtime");

        // Run orchestrator service on default port 9000
        rt.block_on(orchestrator::server::start_http_server(
            project_root.clone(),
            9000,
        ));
    });

    // If validate mode is enabled, run background diagnostics
    if validate_mode {
        tracing::info!("Validation mode enabled - running background diagnostics");
        let diagnostics_handle = std::thread::spawn(|| {
            std::thread::sleep(std::time::Duration::from_millis(1000));
            match orchestrator::diagnostics::run_synchronous_diagnostics(9000) {
                Ok(summary) => {
                    tracing::info!("Background validation complete: {}", summary);
                }
                Err(e) => {
                    tracing::warn!("Background validation warning: {}", e);
                }
            }
        });
        // Don't wait for diagnostics - let it run in background
        let _ = diagnostics_handle;
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            greet,
            invoke_pipeline,
            poll_pipeline_status,
            fetch_pipeline_results,
            check_orchestrator_health,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
