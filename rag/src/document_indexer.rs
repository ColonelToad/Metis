use anyhow::Result;
use serde::{Deserialize, Serialize};
use pyo3::types::PyDict;
use chrono::TimeZone;

use crate::document_store::DocumentStore;
use crate::types::Document;

/// Statistics about indexing run
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IndexingStats {
    pub eia_storage: usize,
    pub eia_prices: usize,
    pub congress_bills: usize,
    pub ferc_orders: usize,
    pub total_documents: usize,
    pub errors: Vec<String>,
    pub timestamp: String,
}

impl Default for IndexingStats {
    fn default() -> Self {
        Self {
            eia_storage: 0,
            eia_prices: 0,
            congress_bills: 0,
            ferc_orders: 0,
            total_documents: 0,
            errors: vec![],
            timestamp: chrono::Utc::now().to_rfc3339(),
        }
    }
}

/// Orchestrates document ingestion and indexing
pub struct DocumentIndexer {
    document_store: std::sync::Arc<tokio::sync::Mutex<DocumentStore>>,
}

impl DocumentIndexer {
    /// Create new indexer
    pub async fn new(document_store: std::sync::Arc<tokio::sync::Mutex<DocumentStore>>) -> Result<Self> {
        Ok(Self { document_store })
    }

    /// Run full ingestion and indexing pipeline
    /// scope: "startup" (full history), "daily_refresh" (recent only)
    pub async fn run_ingestion(&self, scope: &str) -> Result<IndexingStats> {
        let mut stats = IndexingStats::default();

        // Call Python ingestion pipeline
        match self.call_python_ingester(scope).await {
            Ok(docs) => {
                stats.total_documents = docs.len();

                // Index all documents
                if !docs.is_empty() {
                    let mut store = self.document_store.lock().await;
                    match store.index_documents(docs).await {
                        Ok(count) => {
                            tracing::info!("Successfully indexed {} documents", count);
                        }
                        Err(e) => {
                            tracing::error!("Failed to index documents: {}", e);
                            stats.errors.push(format!("Indexing failed: {}", e));
                        }
                    }
                }
            }
            Err(e) => {
                tracing::error!("Python ingestion failed: {}", e);
                stats.errors.push(format!("Ingestion failed: {}", e));
            }
        }

        Ok(stats)
    }

    /// Call Python ingestion pipeline
    async fn call_python_ingester(&self, scope: &str) -> Result<Vec<Document>> {
        let scope_str = scope.to_string();

        let documents = tokio::task::spawn_blocking(move || {
            Self::python_ingest(&scope_str)
        })
        .await??;

        Ok(documents)
    }

    /// Python ingestion (runs in blocking task)
    fn python_ingest(scope: &str) -> Result<Vec<Document>> {
        use pyo3::prelude::*;

        Python::with_gil(|py| {
            // Get current working directory and construct RAG path
            // When running from Tauri (metis/src-tauri), need to go up two levels to reach rag/
            let cwd = std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."));
            
            let rag_path = cwd.parent()
                .and_then(|p| p.parent())
                .map(|p| p.join("rag"))
                .unwrap_or_else(|| cwd.join("rag"))
                .to_string_lossy()
                .to_string();
            
            tracing::info!("Python ingestion - rag_path: {}", rag_path);
            
            // Use new Phase 1 database context loader instead of broken document_ingester
            let code = format!(
                r#"
import sys
import asyncio
import traceback
import os

try:
    # Add RAG module to path
    rag_path = r'{}'
    if rag_path not in sys.path:
        sys.path.insert(0, rag_path)
    
    # Determine correct database path (go up from rag directory)
    rag_parent = os.path.dirname(rag_path)
    db_path = os.path.join(rag_parent, "data", "metis.db")
    
    # Import Phase 1 database context loader using relative import from rag module
    from ingestion.database_context import DatabaseContextLoader
    
    # Create loader and fetch documents
    loader = DatabaseContextLoader(db_path=db_path)
    
    # Get documents based on scope
    async def get_docs():
        result = await loader.ingest_all_sources(scope="{}")
        return result
    
    result = asyncio.run(get_docs())
    
    # Store result for retrieval
    _documents = result["documents"]
    
except Exception as e:
    import sys
    traceback.print_exc(file=sys.stderr)
    raise Exception(f"Ingestion error: {{type(e).__name__}}: {{str(e)}}")
"#,
                rag_path, scope
            );

            // Use run_bound for statements that store results in namespace
            let locals = PyDict::new_bound(py);
            match py.run_bound(&code, Some(&locals), Some(&locals)) {
                Ok(()) => {
                    // Get the _documents variable from the Python namespace
                    let doc_list_obj = locals
                        .get_item("_documents")
                        .map_err(|e| anyhow::anyhow!("Failed to get _documents: {}", e))?
                        .ok_or_else(|| anyhow::anyhow!("_documents not found in Python namespace"))?;
                    let doc_dicts: Vec<std::collections::HashMap<String, String>> = doc_list_obj.extract()?;

                    // Convert Python dicts to Rust Document objects
                    let documents: Result<Vec<Document>> = doc_dicts
                        .into_iter()
                        .map(|dict| {
                            Ok(Document {
                                id: dict.get("id").cloned().unwrap_or_default(),
                                title: dict.get("title").cloned().unwrap_or_default(),
                                content: dict.get("content").cloned().unwrap_or_default(),
                                source: dict.get("source").cloned().unwrap_or_default(),
                                category: dict.get("category").cloned().unwrap_or_default(),
                                timestamp: chrono::DateTime::parse_from_rfc3339(
                                    &dict.get("timestamp").cloned().unwrap_or_else(|| chrono::Utc::now().to_rfc3339()),
                                )
                                .unwrap_or_else(|_| {
                                    chrono::FixedOffset::east_opt(0)
                                        .unwrap()
                                        .from_utc_datetime(
                                            &chrono::DateTime::<chrono::Utc>::from_timestamp(0, 0)
                                                .expect("valid epoch datetime")
                                                .naive_utc(),
                                        )
                                })
                                .with_timezone(&chrono::Utc),
                            })
                        })
                        .collect();

                    documents
                }
                Err(e) => {
                    let error_msg = format!("Python ingestion failed: {}", e);
                    tracing::error!("{}", error_msg);
                    Err(anyhow::anyhow!("{}", error_msg))
                }
            }
        })
    }
}

/// Startup indexing: load all baseline documents
pub async fn startup_index(
    document_store: std::sync::Arc<tokio::sync::Mutex<DocumentStore>>,
) -> Result<IndexingStats> {
    tracing::info!("Starting document indexing (startup mode)");

    let indexer = DocumentIndexer::new(document_store).await?;
    let stats = indexer.run_ingestion("startup").await?;

    tracing::info!("Startup indexing complete: {} documents indexed", stats.total_documents);

    Ok(stats)
}

/// Daily refresh: update with recent documents only
pub async fn daily_refresh(
    document_store: std::sync::Arc<tokio::sync::Mutex<DocumentStore>>,
) -> Result<IndexingStats> {
    tracing::info!("Starting document refresh (daily)");

    let indexer = DocumentIndexer::new(document_store).await?;
    let stats = indexer.run_ingestion("daily_refresh").await?;

    tracing::info!("Daily refresh complete: {} documents indexed", stats.total_documents);

    Ok(stats)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_indexing_stats_default() {
        let stats = IndexingStats::default();
        assert_eq!(stats.total_documents, 0);
        assert!(stats.errors.is_empty());
    }
}
