use anyhow::{anyhow, Result};
use pyo3::prelude::*;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use tracing::info;

/// Result returned from Python orchestration
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PythonPipelineResult {
    pub status: String,
    pub signals: Vec<serde_json::Value>,
    pub metrics: serde_json::Value,
    pub errors: Vec<String>,
}

/// Manages Python execution via PyO3
pub struct PythonRunner {
    project_root: PathBuf,
}

impl PythonRunner {
    pub fn new(project_root: PathBuf) -> Self {
        Self { project_root }
    }

    /// Run the complete pipeline via orchestrate_daily_pipeline.py
    /// Reads METIS_MODE from environment variable
    pub async fn run_pipeline(&self) -> Result<PythonPipelineResult> {
        info!("Running complete pipeline via PyO3");

        let project_root = self.project_root.clone();

        let result = tokio::task::spawn_blocking(move || {
            Python::with_gil(|py| {
                // Add project root to path so we can import research modules
                let sys = py.import_bound("sys")?;
                let path = sys.getattr("path")?;
                path.call_method1("insert", (0, project_root.to_string_lossy().to_string()))?;

                // Import the orchestration module from research folder
                let orchestrate_module = py.import_bound("research.orchestrate_daily_pipeline")?;

                // Call main function - it reads METIS_MODE from environment
                let main_func = orchestrate_module.getattr("main")?;
                let py_result = main_func.call0()?;

                // Convert Python dict to JSON string, then parse
                let json_module = py.import_bound("json")?;
                let dumps = json_module.getattr("dumps")?;
                let json_str: String = dumps.call1((py_result,))?.extract()?;

                let result_dict: serde_json::Value =
                    serde_json::from_str(&json_str).map_err(|e| {
                        pyo3::exceptions::PyRuntimeError::new_err(format!(
                            "JSON parse error: {}",
                            e
                        ))
                    })?;

                // Extract fields
                let status = result_dict["status"]
                    .as_str()
                    .ok_or_else(|| {
                        pyo3::exceptions::PyRuntimeError::new_err("Missing 'status' field")
                    })?
                    .to_string();

                let signals = result_dict["signals"]
                    .as_array()
                    .ok_or_else(|| {
                        pyo3::exceptions::PyRuntimeError::new_err("Missing 'signals' field")
                    })?
                    .clone();

                let metrics = result_dict["metrics"].clone();

                let errors = result_dict["errors"]
                    .as_array()
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|v| v.as_str().map(|s| s.to_string()))
                            .collect()
                    })
                    .unwrap_or_default();

                Ok::<PythonPipelineResult, PyErr>(PythonPipelineResult {
                    status,
                    signals,
                    metrics,
                    errors,
                })
            })
        })
        .await
        .map_err(|e| anyhow!("Task join error: {}", e))??;

        Ok(result)
    }

    /// Run only data ingestion phase
    pub async fn run_ingestion(&self) -> Result<()> {
        info!("Running ingestion phase via PyO3");

        let project_root = self.project_root.clone();

        tokio::task::spawn_blocking(move || {
            Python::with_gil(|py| {
                // Add project root to path
                let sys = py.import_bound("sys")?;
                let path = sys.getattr("path")?;
                path.call_method1("insert", (0, project_root.to_string_lossy().to_string()))?;

                // Import and call ingest
                let module = py.import_bound("research.data_ingest.run_all_ingesters")?;
                module.call_method0("main")?;

                Ok::<(), PyErr>(())
            })
        })
        .await
        .map_err(|e| anyhow!("Task join error: {}", e))??;

        info!("Ingestion phase completed");
        Ok(())
    }

    /// Run only features phase
    pub async fn run_features(&self) -> Result<()> {
        info!("Running features phase via PyO3");

        let project_root = self.project_root.clone();

        tokio::task::spawn_blocking(move || {
            Python::with_gil(|py| {
                // Add project root to path
                let sys = py.import_bound("sys")?;
                let path = sys.getattr("path")?;
                path.call_method1("insert", (0, project_root.to_string_lossy().to_string()))?;

                // Import and call features
                let module = py.import_bound("research.models.unify_features")?;
                module.call_method0("main")?;

                Ok::<(), PyErr>(())
            })
        })
        .await
        .map_err(|e| anyhow!("Task join error: {}", e))??;

        info!("Features phase completed");
        Ok(())
    }

    /// Run only inference phase
    pub async fn run_inference(&self) -> Result<()> {
        info!("Running inference phase via PyO3");

        let project_root = self.project_root.clone();

        tokio::task::spawn_blocking(move || {
            Python::with_gil(|py| {
                // Add project root to path
                let sys = py.import_bound("sys")?;
                let path = sys.getattr("path")?;
                path.call_method1("insert", (0, project_root.to_string_lossy().to_string()))?;

                // Import DualLSTMInference
                let module = py.import_bound("research.models.inference_pipeline")?;
                let inference_class = module.getattr("DualLSTMInference")?;

                // Create instance with PyDict in PyO3 0.22+ way
                // Build absolute paths for model, scalers, and config
                let model_path = project_root.join("models").join("lstm_ng_predictor.keras");
                let scalers_path = project_root
                    .join("research")
                    .join("models")
                    .join("config")
                    .join("scalers_v1.0.pkl");
                let config_path = project_root
                    .join("research")
                    .join("models")
                    .join("config")
                    .join("model_config.yaml");

                let kwargs = pyo3::types::PyDict::new_bound(py);
                kwargs.set_item("model_path", model_path.to_string_lossy().to_string())?;
                kwargs.set_item("scalers_path", scalers_path.to_string_lossy().to_string())?;
                kwargs.set_item("config_path", config_path.to_string_lossy().to_string())?;
                kwargs.set_item("signal_host", "localhost")?;
                kwargs.set_item("signal_port", 8080)?;
                kwargs.set_item("threshold", 0.40)?;

                let _pipeline = inference_class.call((), Some(&kwargs))?;

                Ok::<(), PyErr>(())
            })
        })
        .await
        .map_err(|e| anyhow!("Task join error: {}", e))??;

        info!("Inference phase completed");
        Ok(())
    }
}
