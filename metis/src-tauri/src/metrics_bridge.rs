/// Metrics bridge - calls Python service to query metrics
/// Similar to pipeline_bridge.rs but for metrics queries

use std::process::Command;
use std::path::PathBuf;
use serde_json::{json, Value};
use tracing::{error, info};

/// Call Python metrics service and parse JSON response
fn call_metrics_service(command: &str, _args: &[&str]) -> Result<Value, String> {
    // Build inline Python code to execute metrics queries
    let python_code = format!(
        r#"
import json
import sys
from pathlib import Path

# Add project root to path
project_root = Path.cwd()
sys.path.insert(0, str(project_root))

try:
    from research.metrics_service import MetricsService
    
    service = MetricsService()
    
    if '{}' == 'dashboard':
        result = service.get_dashboard_summary()
    elif '{}' == 'recent':
        result = service.get_recent_runs(limit=20)
    elif '{}' == 'health':
        result = service.get_ingester_health(days=7)
    elif '{}' == 'failures':
        result = service.get_failures(days=7)
    else:
        result = {{"error": "Unknown command"}}
    
    print(json.dumps(result, default=str))
except Exception as e:
    import traceback
    print(json.dumps({{"error": str(e), "traceback": traceback.format_exc()}}))
    sys.exit(1)
"#,
        command, command, command, command
    );
    
    // Execute Python from project root so it can find research/ folder
    let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| PathBuf::from("."));
    
    let output = Command::new("python")
        .current_dir(project_root)
        .arg("-c")
        .arg(&python_code)
        .output()
        .map_err(|e| {
            error!("Failed to call metrics service: {}", e);
            format!("Failed to call metrics service: {}", e)
        })?;
    
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        error!("Metrics service error: {}", stderr);
        return Err(format!("Metrics query failed: {}", stderr));
    }
    
    let stdout = String::from_utf8_lossy(&output.stdout);
    match serde_json::from_str::<Value>(&stdout) {
        Ok(json_result) => {
            info!("Metrics query succeeded: {}", command);
            Ok(json_result)
        }
        Err(e) => {
            error!("Failed to parse metrics response: {}", e);
            Err(format!("Failed to parse metrics response: {}", e))
        }
    }
}

/// Get dashboard summary for AdminScreen
pub async fn get_dashboard_summary() -> Result<Value, String> {
    info!("Fetching dashboard summary");
    call_metrics_service("dashboard", &[])
}

/// Get recent runs
pub async fn get_recent_runs(limit: u32) -> Result<Value, String> {
    info!("Fetching recent runs: limit={}", limit);
    
    // For now, just get dashboard which includes recent runs
    // Could extend to separate call if needed
    call_metrics_service("recent", &[])
}

/// Get ingester health
pub async fn get_ingester_health(days: u32) -> Result<Value, String> {
    info!("Fetching ingester health: days={}", days);
    call_metrics_service("health", &[])
}

/// Get recent failures
pub async fn get_failures(days: u32) -> Result<Value, String> {
    info!("Fetching failures: days={}", days);
    call_metrics_service("failures", &[])
}

/// Verify metrics service is accessible
pub async fn check_metrics_available() -> Result<Value, String> {
    match call_metrics_service("health", &[]) {
        Ok(_) => Ok(json!({"status": "available"})),
        Err(e) => {
            error!("Metrics service not available: {}", e);
            Ok(json!({"status": "unavailable", "error": e}))
        }
    }
}
