use anyhow::{anyhow, Result};
use pyo3::prelude::*;
use std::thread;
use tokio::sync::{mpsc, oneshot};

use crate::types::Document;

/// Commands sent from async Rust to the dedicated Python thread
pub enum PythonCommand {
    EmbedText {
        text: String,
        responder: oneshot::Sender<Result<Vec<f32>>>,
    },
    HealthCheck {
        responder: oneshot::Sender<Result<bool>>,
    },
}

pub struct PythonRAGBridge {
    sender: mpsc::Sender<PythonCommand>,
}

impl PythonRAGBridge {
    /// Initialize the Python RAG bridge and spin up the dedicated OS thread
    pub fn new() -> Result<Self> {
        let (tx, mut rx) = mpsc::channel::<PythonCommand>(32);

        thread::spawn(move || {
            // ==========================================================
            // 1. ONE-TIME INITIALIZATION
            // Grab the GIL just to set up sys.path, then release it.
            // ==========================================================
            Python::with_gil(|py| {
                crate::python_env::setup_sys_path(py);
            });

            // ==========================================================
            // 2. THE EVENT LOOP
            // Wait for messages natively. DO NOT hold the GIL here!
            // ==========================================================
            while let Some(cmd) = rx.blocking_recv() {
                match cmd {
                    PythonCommand::EmbedText { text, responder } => {
                        // Only grab the GIL for the exact moment of execution
                        let result = Python::with_gil(|py| Self::execute_embed(py, &text));
                        let _ = responder.send(result);
                    }
                    PythonCommand::HealthCheck { responder } => {
                        let _ = responder.send(Ok(true));
                    }
                }
            }
        });

        Ok(Self { sender: tx })
    }

    // ==========================================================
    // ASYNC PUBLIC API (Called by your main Rust app)
    // ==========================================================

    pub async fn embed_text(&self, text: &str) -> Result<Vec<f32>> {
        let (resp_tx, resp_rx) = oneshot::channel();

        self.sender
            .send(PythonCommand::EmbedText {
                text: text.to_string(),
                responder: resp_tx,
            })
            .await
            .map_err(|_| anyhow!("Python thread died or channel closed"))?;

        resp_rx
            .await
            .map_err(|e| anyhow!("Failed to receive response: {}", e))?
    }

    pub async fn index_documents(&self, _docs: Vec<Document>) -> Result<usize> {
        Ok(_docs.len())
    }

    pub async fn health_check(&self) -> Result<bool> {
        let (resp_tx, resp_rx) = oneshot::channel();
        self.sender
            .send(PythonCommand::HealthCheck { responder: resp_tx })
            .await?;
        resp_rx.await?
    }

    // ==========================================================
    // PRIVATE SYNCHRONOUS HELPERS (Run ONLY on the Python Thread)
    // ==========================================================

    fn execute_embed(py: Python, text: &str) -> Result<Vec<f32>> {
        let escaped = text
            .replace('\\', "\\\\")
            .replace('"', "\\\"")
            .replace('\n', "\\n")
            .replace('\r', "\\r")
            .replace('\t', "\\t")
            .replace('\x00', "\\x00");

        let code = format!(
            r#"
import os
import warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
warnings.filterwarnings('ignore')

try:
    import sys
    if not hasattr(sys, '_cached_sentence_model'):
        from sentence_transformers import SentenceTransformer
        sys._cached_sentence_model = SentenceTransformer('all-MiniLM-L6-v2')
    
    embedding = sys._cached_sentence_model.encode("{}")
    __embedding_result__ = list(embedding)
except Exception as e:
    import traceback
    traceback.print_exc()
    raise Exception(f"Embedding failed: {{str(e)}}")
"#,
            escaped
        );
        py.run_bound(&code, None, None)
            .map_err(|e| anyhow!("Embed failed: {}", e))?;
        py.eval_bound("__embedding_result__", None, None)
            .map_err(|e| anyhow!("Embed result retrieval failed: {}", e))?
            .extract::<Vec<f32>>()
            .map_err(|e| anyhow!("Extract failed: {}", e))
    }

}
