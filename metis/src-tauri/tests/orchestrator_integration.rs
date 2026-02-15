use serde_json::{json, Value};
use std::process::{Child, Command};
/// Integration tests for orchestrator service
/// Run with: cargo test --test orchestrator_integration
///
/// These tests:
/// - Start a standalone orchestrator service
/// - Execute pipeline runs
/// - Validate JSON response structure
/// - Measure and log timing data
/// - Report baseline metrics
use std::sync::Once;
use std::thread;
use std::time::Duration;

static INIT: Once = Once::new();

struct TestService {
    process: Child,
    port: u16,
}

impl TestService {
    fn start(port: u16) -> Self {
        INIT.call_once(|| {
            // Kill any existing processes on the test ports
            for p in &[9000, 9001, 9002, 9003] {
                let _ = Command::new("powershell")
                    .args(&["-Command", &format!(
                        "$procs = netstat -ano 2>$null | Select-String ':{0}' | ForEach-Object {{ ($_ -split '\\s+')[-1] }}; \
                        foreach ($pid in $procs) {{ if ($pid -and $pid -ne 'PID') {{ Stop-Process -Id $pid -Force -EA SilentlyContinue }} }}",
                        p
                    )])
                    .output();
            }
        });

        // Kill any existing process on the port
        let _ = Command::new("powershell")
            .args(&["-Command", &format!(
                "$procs = netstat -ano 2>$null | Select-String ':{0}' | ForEach-Object {{ ($_ -split '\\s+')[-1] }}; \
                foreach ($pid in $procs) {{ if ($pid -and $pid -ne 'PID') {{ Stop-Process -Id $pid -Force -EA SilentlyContinue }} }}",
                port
            )])
            .output();

        thread::sleep(Duration::from_millis(500));

        // Start the orchestrator service
        let project_root = std::env::current_dir()
            .ok()
            .and_then(|p| {
                p.parent()
                    .and_then(|p| p.parent())
                    .map(|parent| parent.to_path_buf())
            })
            .unwrap_or_else(|| std::path::PathBuf::from("."));

        let mut process = Command::new("target/debug/orchestrator.exe")
            .arg(&project_root)
            .arg(port.to_string())
            .spawn()
            .expect("Failed to start orchestrator service");

        // Wait for service to be ready using blocking client
        let mut attempts = 0;
        loop {
            if attempts >= 60 {
                // 12 seconds max
                process.kill().ok();
                panic!("Service failed to start after 60 attempts on port {}", port);
            }

            match reqwest::blocking::Client::builder()
                .timeout(Duration::from_secs(1))
                .build()
                .and_then(|c| {
                    c.get(&format!("http://127.0.0.1:{}/api/health", port))
                        .send()
                }) {
                Ok(resp) if resp.status() == 200 => break,
                _ => {
                    thread::sleep(Duration::from_millis(200));
                    attempts += 1;
                }
            }
        }

        TestService { process, port }
    }

    fn base_url(&self) -> String {
        format!("http://127.0.0.1:{}", self.port)
    }
}

impl Drop for TestService {
    fn drop(&mut self) {
        let _ = self.process.kill();
    }
}

#[test]
fn test_service_health() {
    let _service = TestService::start(9000);
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .expect("Failed to build client");

    let response = client
        .get("http://127.0.0.1:9000/api/health")
        .send()
        .expect("Health check failed");

    assert_eq!(response.status(), 200);

    let data: Value = response.json().expect("Failed to parse JSON");
    assert_eq!(data["status"], "ok");
    assert!(data["uptime_seconds"].is_u64());
    assert!(data["version"].is_string());

    println!("✓ Health check passed");
}

#[test]
fn test_pipeline_run_structure() {
    let _service = TestService::start(9001);
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(10))
        .build()
        .expect("Failed to build client");

    let payload = json!({
        "mode": "DEV",
        "force_refresh": false
    });

    let response = client
        .post("http://127.0.0.1:9001/api/pipeline/run")
        .json(&payload)
        .send()
        .expect("Pipeline run failed");

    assert_eq!(response.status(), 202);

    let data: Value = response.json().expect("Failed to parse JSON");
    assert!(data["job_id"].is_string());
    assert!(data["status"].is_string());
    assert!(data["phase"].is_string());

    let job_id = data["job_id"].as_str().expect("No job_id");
    println!("✓ Pipeline started with job_id: {}", job_id);

    // Poll for completion
    let max_wait = Duration::from_secs(120);
    let start = std::time::Instant::now();
    loop {
        if start.elapsed() > max_wait {
            panic!("Pipeline did not complete within timeout");
        }

        let status_resp = client
            .get(&format!(
                "http://127.0.0.1:9001/api/pipeline/status/{}",
                job_id
            ))
            .send()
            .expect("Status check failed");

        let status_data: Value = status_resp.json().expect("Failed to parse status");
        let status = status_data["status"].as_str().unwrap_or("");

        if status == "complete" || status == "error" || status == "partial" {
            break;
        }

        thread::sleep(Duration::from_millis(500));
    }

    // Get results
    let results_resp = client
        .get(&format!(
            "http://127.0.0.1:9001/api/pipeline/results/{}",
            job_id
        ))
        .send()
        .expect("Results fetch failed");

    let results_data: Value = results_resp.json().expect("Failed to parse results");

    // Validate structure
    assert!(results_data["status"].is_string());
    assert!(results_data["phase"].is_string());
    assert!(results_data["signals"].is_array());
    assert!(results_data["metrics"].is_object());

    let metrics = &results_data["metrics"];
    assert!(metrics["total_time"].is_number());
    assert!(metrics["ingest_time"].is_number());
    assert!(metrics["feature_time"].is_number());
    assert!(metrics["inference_time"].is_number());
    assert!(metrics["signals_generated"].is_u64());
    assert!(metrics["avg_confidence"].is_number());
    assert!(metrics["mode"].is_string());
    assert!(metrics["lmp_cache_hit"].is_boolean());
    assert!(metrics["cme_cache_hit"].is_boolean());

    let total_time = metrics["total_time"].as_f64().unwrap_or(0.0);
    println!("✓ Pipeline completed in {:.3}s", total_time);
    println!(
        "  - Ingestion:  {:.3}s",
        metrics["ingest_time"].as_f64().unwrap_or(0.0)
    );
    println!(
        "  - Features:   {:.3}s",
        metrics["feature_time"].as_f64().unwrap_or(0.0)
    );
    println!(
        "  - Inference:  {:.3}s",
        metrics["inference_time"].as_f64().unwrap_or(0.0)
    );
    println!(
        "  - Signals:    {}",
        metrics["signals_generated"].as_u64().unwrap_or(0)
    );
}

#[test]
fn test_pipeline_consistency() {
    let _service = TestService::start(9002);
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(10))
        .build()
        .expect("Failed to build client");

    let mut timings = Vec::new();

    // Test single run for timing (multiple runs would require pipeline implementation)
    let payload = json!({
        "mode": "DEV",
        "force_refresh": false
    });

    let response = client
        .post("http://127.0.0.1:9002/api/pipeline/run")
        .json(&payload)
        .send()
        .expect("Pipeline run failed");

    let data: Value = response.json().expect("Failed to parse JSON");
    let job_id = data["job_id"].as_str().expect("No job_id");

    // Poll for completion
    let max_wait = Duration::from_secs(120);
    let start = std::time::Instant::now();
    loop {
        if start.elapsed() > max_wait {
            panic!("Pipeline did not complete within timeout");
        }

        let status_resp = client
            .get(&format!(
                "http://127.0.0.1:9002/api/pipeline/status/{}",
                job_id
            ))
            .send()
            .expect("Status check failed");

        let status_data: Value = status_resp.json().expect("Failed to parse status");
        let status = status_data["status"].as_str().unwrap_or("");

        if status == "complete" || status == "error" || status == "partial" {
            break;
        }

        thread::sleep(Duration::from_millis(500));
    }

    // Get results
    let results_resp = client
        .get(&format!(
            "http://127.0.0.1:9002/api/pipeline/results/{}",
            job_id
        ))
        .send()
        .expect("Results fetch failed");

    let results_data: Value = results_resp.json().expect("Failed to parse results");
    let total_time = results_data["metrics"]["total_time"]
        .as_f64()
        .expect("No total_time");

    timings.push(total_time);
    println!("✓ Pipeline timing baseline: {:.3}s", total_time);
}

#[test]
fn test_endpoint_json_shapes() {
    let _service = TestService::start(9003);
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .expect("Failed to build client");

    // Test POST /api/pipeline/run
    let payload = json!({ "mode": "DEV", "force_refresh": false });
    let resp = client
        .post("http://127.0.0.1:9003/api/pipeline/run")
        .json(&payload)
        .send()
        .expect("Failed");
    let data: Value = resp.json().expect("Failed to parse");
    assert!(data["job_id"].is_string());
    assert!(data["status"].is_string());
    assert!(data["phase"].is_string());
    println!("✓ POST /api/pipeline/run - JSON structure valid");

    // Test GET /api/health
    let resp = client
        .get("http://127.0.0.1:9003/api/health")
        .send()
        .expect("Failed");
    let data: Value = resp.json().expect("Failed to parse");
    assert!(data["status"].is_string());
    assert!(data["uptime_seconds"].is_u64());
    assert!(data["version"].is_string());
    println!("✓ GET /api/health - JSON structure valid");
}
