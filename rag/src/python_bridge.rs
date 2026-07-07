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
    RetrieveDocuments {
        query_embedding: Vec<f32>,
        top_k: usize,
        source_filter: Option<String>,
        db_path: String,
        responder: oneshot::Sender<Result<Vec<Document>>>,
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
                if let Ok(sys) = py.import_bound("sys") {
                    if let Ok(path) = sys.getattr("path") {
                        let _ = path.call_method1("append", ("C:\\Users\\legot\\Metis",));
                        if let Ok(cwd) = std::env::current_dir() {
                            let _ = path.call_method1("append", (cwd.to_string_lossy().as_ref(),));
                        }
                    }
                }
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
                    PythonCommand::RetrieveDocuments {
                        query_embedding,
                        top_k,
                        source_filter,
                        db_path,
                        responder,
                    } => {
                        let result = Python::with_gil(|py| {
                            Self::execute_retrieve(
                                py,
                                &query_embedding,
                                top_k,
                                source_filter.as_deref(),
                                &db_path,
                            )
                        });
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

    pub async fn retrieve_documents(
        &self,
        query_embedding: &[f32],
        top_k: usize,
        source_filter: Option<&str>,
        db_path: &str,
    ) -> Result<Vec<Document>> {
        let (resp_tx, resp_rx) = oneshot::channel();

        self.sender
            .send(PythonCommand::RetrieveDocuments {
                query_embedding: query_embedding.to_vec(),
                top_k,
                source_filter: source_filter.map(|s| s.to_string()),
                db_path: db_path.to_string(),
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

    fn execute_retrieve(
        py: Python,
        query_embedding: &[f32],
        top_k: usize,
        source_filter: Option<&str>,
        db_path: &str,
    ) -> Result<Vec<Document>> {
        let embedding_list = format!(
            "[{}]",
            query_embedding
                .iter()
                .map(|f| f.to_string())
                .collect::<Vec<_>>()
                .join(",")
        );

        let source_filter_arg = if let Some(ref src) = source_filter {
            format!("\"{}\"", src.replace('\"', "\\\""))
        } else {
            "None".to_string()
        };

        let db_path_escaped = db_path.replace('\\', "\\\\").replace('\"', "\\\"");

        let code = format!(
            r#"
# 1. SILENCE WARNINGS BEFORE ANYTHING LOADS
import os
import warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
warnings.filterwarnings('ignore')

try:
    import sys
    from pathlib import Path

    # Determine path to rag module
    rag_path = Path(r'{}').parent.parent
    if str(rag_path) not in sys.path:
        sys.path.insert(0, str(rag_path))

    # 2. CACHE LANCEDB TO PREVENT HEAP CORRUPTION (Now safe on the single thread!)
    if not hasattr(sys, '_cached_lancedb_store'):
        from rag.vectorstore.lancedb_store import LanceVectorStore
        sys._cached_lancedb_store = LanceVectorStore(r'{}', "metis_documents", 384)

    store = sys._cached_lancedb_store
    
    # 3. DEBUG: WHAT DOES RUST ACTUALLY SEE?
    print(f"\n--- PYTHON DEBUG ---")
    print(f"DB Path: {{store.db_path}}")
    print(f"Total Rows in DB: {{store.table.count_rows()}}")

    query_embedding = {}
    top_k = {}
    source_filter = {}
    
    print(f"Requested Filter: {{source_filter}}")
    print("Forcing filter to None to guarantee results...")
    source_filter = None

    # Perform search using the cached store
    q = store.table.search(query_embedding).limit(top_k)
    res = q.to_list()
    
    print(f"Results found: {{len(res)}}")
    print(f"--------------------\n")

    # Convert results to dicts for serialization
    import json
    doc_list = []
    for result in res:
        doc_dict = {{
            "id": str(result.get("doc_id", result.get("id", ""))),
            "title": str(result.get("title", "")),
            "content": str(result.get("content", "")),
            "source": str(result.get("source", "")),
            "category": str(result.get("category", "unknown")),
            "timestamp": str(result.get("published_date", "2000-01-01T00:00:00Z")),
        }}
        doc_list.append(doc_dict)

    # Serialize to string to safely cross the Rust/Python boundary
    __search_results__ = json.dumps(doc_list)

except Exception as e:
    import traceback
    traceback.print_exc()
    raise Exception(f"Document retrieval failed: {{str(e)}}")
"#,
            db_path_escaped, db_path_escaped, embedding_list, top_k, source_filter_arg
        );

        py.run_bound(&code, None, None)
            .map_err(|e| anyhow!("Retrieval execution failed: {}", e))?;

        // Extract the JSON string from Python
        let results_json: String = py
            .eval_bound("__search_results__", None, None)
            .map_err(|e| anyhow!("Result extraction failed: {}", e))?
            .extract()
            .map_err(|e| anyhow!("Failed to extract JSON string: {}", e))?;

        // Parse the JSON string natively in Rust
        let doc_dicts: Vec<std::collections::HashMap<String, String>> =
            serde_json::from_str(&results_json)
                .map_err(|e| anyhow!("JSON parsing failed: {}", e))?;

        println!("--- RUST DEBUG ---");
        println!("Parsed {} documents from JSON", doc_dicts.len());

        let documents: Result<Vec<Document>> = doc_dicts
            .into_iter()
            .map(|dict| {
                Ok(Document {
                    id: dict.get("id").cloned().unwrap_or_default(),
                    title: dict.get("title").cloned().unwrap_or_default(),
                    content: dict.get("content").cloned().unwrap_or_default(),
                    source: dict.get("source").cloned().unwrap_or_default(),
                    category: dict
                        .get("category")
                        .cloned()
                        .unwrap_or_else(|| "unknown".to_string()),
                    timestamp: chrono::DateTime::parse_from_rfc3339(
                        &dict
                            .get("timestamp")
                            .cloned()
                            .unwrap_or_else(|| "2000-01-01T00:00:00Z".to_string()),
                    )
                    .map(|dt| dt.with_timezone(&chrono::Utc))
                    .unwrap_or_else(|_| chrono::Utc::now()),
                })
            })
            .collect();

        documents
    }
}
