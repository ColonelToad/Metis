// Rust-callable test coordinator bridge
// Spawns Python subprocess to run coordinator methods

use std::process::Command;
use std::path::PathBuf;
use serde_json::Value;


pub async fn run_test_suite(suite_id: String) -> Result<Value, String> {
    invoke_coordinator("run_suite", &serde_json::json!({ "suite_id": suite_id })).await
}


pub async fn list_test_suites() -> Result<Value, String> {
    invoke_coordinator("list_suites", &serde_json::json!({})).await
}


pub async fn get_test_status(run_id: String) -> Result<Value, String> {
    invoke_coordinator("get_status", &serde_json::json!({ "run_id": run_id })).await
}


pub async fn get_test_results(run_id: String) -> Result<Value, String> {
    invoke_coordinator("get_results", &serde_json::json!({ "run_id": run_id })).await
}


pub async fn get_active_tests() -> Result<Value, String> {
    invoke_coordinator("get_active", &serde_json::json!({})).await
}


async fn invoke_coordinator(method: &str, params: &Value) -> Result<Value, String> {
    // Call Python test coordinator via subprocess
    // Current dir will be project root where research/ exists
    
    // Build Python command
    let python_code = format!(
        r#"
import json
import sys
sys.path.insert(0, '.')

from research.test_coordinator import TestCoordinator

coordinator = TestCoordinator()

try:
    method = '{}'
    suite_id = '{}'
    run_id = '{}'
    
    if method == 'run_suite':
        run_id = coordinator.run_suite(suite_id)
        print(json.dumps({{"success": True, "run_id": run_id}}))
    elif method == 'list_suites':
        suites = coordinator.list_suites()
        print(json.dumps({{"success": True, "suites": suites}}))
    elif method == 'get_status':
        status = coordinator.get_test_status(run_id)
        print(json.dumps({{"success": True, **status}}))
    elif method == 'get_results':
        results = coordinator.get_test_results(run_id)
        print(json.dumps({{"success": True, **results}}))
    elif method == 'get_active':
        tests = coordinator.get_active_tests()
        print(json.dumps({{"success": True, "tests": tests}}))
except Exception as e:
    print(json.dumps({{"success": False, "error": str(e)}}))
    sys.exit(1)
"#,
        method,
        params.get("suite_id").and_then(|v| v.as_str()).unwrap_or(""),
        params.get("run_id").and_then(|v| v.as_str()).unwrap_or("")
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
        .map_err(|e| format!("Failed to spawn coordinator: {}", e))?;
    
    // Parse output
    if output.status.success() {
        let stdout = String::from_utf8_lossy(&output.stdout);
        serde_json::from_str(&stdout)
            .map_err(|e| format!("Invalid JSON from coordinator: {}", e))
    } else {
        let stderr = String::from_utf8_lossy(&output.stderr);
        Err(format!("Coordinator error: {}", stderr))
    }
}
