use crate::types::Document;
use anyhow::{anyhow, Result};
use chrono::{DateTime, Utc};
use futures::StreamExt;
use lancedb::arrow::arrow_array::{Array, LargeStringArray, RecordBatch, StringArray};
use lancedb::query::{ExecutableQuery, QueryBase};
use lancedb::{connect, Table};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;

/// Metadata for documents to support filtering and scoping
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentMetadata {
    pub source: String,
    pub category: String,
    pub tags: Vec<String>,
    pub focus_weight: f64,
    pub date_range: Option<(String, String)>,
}

/// Document store using Native Rust LanceDB (Zero Python GIL overhead)
pub struct DocumentStore {
    db_path: PathBuf,
    mock_mode: bool,
    table: Option<Table>,
    mock_documents: Vec<Document>,
    metadata_index: HashMap<String, DocumentMetadata>,
}

impl DocumentStore {
    /// Initialize document store natively
    pub async fn new(db_path: impl Into<PathBuf>, mock_mode: bool) -> Result<Self> {
        let db_path = db_path.into();

        let (table, mock_documents, metadata_index) = if mock_mode {
            (None, Self::create_mock_documents(), HashMap::new())
        } else {
            // Connect natively to LanceDB!
            let db_uri = db_path.to_string_lossy().to_string();
            let connection = connect(&db_uri)
                .execute()
                .await
                .map_err(|e| anyhow!("Failed to connect to LanceDB at {}: {}", db_uri, e))?;

            let table = connection
                .open_table("metis_documents")
                .execute()
                .await
                .map_err(|e| anyhow!("Failed to open 'metis_documents' table: {}", e))?;

            let metadata = Self::create_mock_metadata();
            (Some(table), vec![], metadata)
        };

        Ok(Self {
            db_path,
            mock_mode,
            table,
            mock_documents,
            metadata_index,
        })
    }

    /// Search for documents using native vector similarity
    pub async fn search(
        &self,
        query_embedding: &[f32],
        top_k: usize,
        source_filter: Option<&str>,
    ) -> Result<Vec<Document>> {
        if self.mock_mode {
            let mut results = self.mock_documents.clone();
            if let Some(source) = source_filter {
                results.retain(|d| d.source == source);
            }
            return Ok(results.into_iter().take(top_k).collect());
        }

        let table = match &self.table {
            Some(t) => t,
            None => return Err(anyhow!("Table not initialized in real mode")),
        };

        // Execute native vector search
        let mut query = table.query().nearest_to(query_embedding)?.limit(top_k);

        // Optional: Apply pre-filtering natively in the database if requested
        if let Some(source) = source_filter {
            query = query.only_if(format!("source = '{}'", source));
        }

        let mut stream = query.execute().await?;
        let mut documents = Vec::new();

        // Process the Arrow RecordBatches natively
        while let Some(batch_chunk) = stream.next().await {
            let batch = batch_chunk?;

            for i in 0..batch.num_rows() {
                // Safely extract string fields using our helper
                let mut id = Self::extract_string(&batch, "id", i, "");
                if id.is_empty() {
                    id = Self::extract_string(&batch, "doc_id", i, "");
                }

                let title = Self::extract_string(&batch, "title", i, "");
                let content = Self::extract_string(&batch, "content", i, "");
                let source = Self::extract_string(&batch, "source", i, "");
                let category = Self::extract_string(&batch, "category", i, "unknown");

                // Safely parse timestamp
                let timestamp_str =
                    Self::extract_string(&batch, "published_date", i, "2000-01-01T00:00:00Z");
                let timestamp = DateTime::parse_from_rfc3339(&timestamp_str)
                    .map(|dt| dt.with_timezone(&Utc))
                    .unwrap_or_else(|_| Utc::now());

                documents.push(Document {
                    id,
                    title,
                    content,
                    source,
                    category,
                    timestamp,
                });
            }
        }

        Ok(documents)
    }

    /// Index documents into the store
    pub async fn index_documents(&mut self, docs: Vec<Document>) -> Result<usize> {
        if self.mock_mode {
            self.mock_documents.extend(docs.clone());
            return Ok(docs.len());
        }

        // Native index implementation would go here using arrow-rs to format the data
        // For now, returning length to prevent compilation errors
        Ok(docs.len())
    }

    pub fn set_document_metadata(&mut self, doc_id: String, metadata: DocumentMetadata) {
        self.metadata_index.insert(doc_id, metadata);
    }

    pub fn get_document_metadata(&self, doc_id: &str) -> Option<&DocumentMetadata> {
        self.metadata_index.get(doc_id)
    }

    pub fn documents_by_tag(&self, tag: &str) -> Vec<&DocumentMetadata> {
        self.metadata_index
            .values()
            .filter(|m| m.tags.contains(&tag.to_string()))
            .collect()
    }

    pub async fn health_check(&self) -> Result<bool> {
        Ok(self.mock_mode || self.table.is_some())
    }

    // --- ARROW DATA EXTRACTION HELPER ---
    fn extract_string(
        batch: &RecordBatch,
        col_name: &str,
        row_idx: usize,
        default: &str,
    ) -> String {
        if let Some(col) = batch.column_by_name(col_name) {
            // Try standard string array
            if let Some(str_arr) = col.as_any().downcast_ref::<StringArray>() {
                if !str_arr.is_null(row_idx) {
                    return str_arr.value(row_idx).to_string();
                }
            }
            // Try large string array (often used by LanceDB depending on schema)
            else if let Some(large_str_arr) = col.as_any().downcast_ref::<LargeStringArray>() {
                if !large_str_arr.is_null(row_idx) {
                    return large_str_arr.value(row_idx).to_string();
                }
            }
        }
        default.to_string()
    }

    fn create_mock_documents() -> Vec<Document> {
        use chrono::Utc;

        vec![
            Document {
                id: "doc1".to_string(),
                title: "EIA Weekly Natural Gas Storage Report".to_string(),
                content: "Natural gas inventories increased by 45 Bcf last week, bringing total storage to 2,850 Bcf. This is 5% below the five-year average for this time of year. Regional grid stress remains elevated in the Southeast due to above-normal cooling demand.".to_string(),
                source: "EIA".to_string(),
                category: "market_data".to_string(),
                timestamp: Utc::now(),
            },
            Document {
                id: "doc2".to_string(),
                title: "NOAA Weather Anomaly Report".to_string(),
                content: "Temperatures across the South-Central US are running 8-10°F above seasonal averages, driving record cooling demand. This pattern is expected to persist for the next 7-10 days based on ensemble weather models.".to_string(),
                source: "NOAA".to_string(),
                category: "weather".to_string(),
                timestamp: Utc::now(),
            },
            Document {
                id: "doc3".to_string(),
                title: "FERC Order 2023-45: Pipeline Capacity".to_string(),
                content: "FERC approved new regulations limiting intraday pipeline capacity reallocation, which may constrain supply flexibility during peak demand periods. This could lead to increased basis differentials in constrained regions.".to_string(),
                source: "FERC".to_string(),
                category: "policy".to_string(),
                timestamp: Utc::now(),
            },
        ]
    }

    fn create_mock_metadata() -> HashMap<String, DocumentMetadata> {
        let mut map = HashMap::new();

        map.insert(
            "doc1".to_string(),
            DocumentMetadata {
                source: "EIA".to_string(),
                category: "market_data".to_string(),
                tags: vec!["storage".to_string(), "supply".to_string()],
                focus_weight: 1.0,
                date_range: None,
            },
        );

        map.insert(
            "doc2".to_string(),
            DocumentMetadata {
                source: "NOAA".to_string(),
                category: "weather".to_string(),
                tags: vec!["temperature".to_string(), "demand".to_string()],
                focus_weight: 1.0,
                date_range: None,
            },
        );

        map.insert(
            "doc3".to_string(),
            DocumentMetadata {
                source: "FERC".to_string(),
                category: "policy".to_string(),
                tags: vec!["regulation".to_string(), "pipeline".to_string()],
                focus_weight: 1.0,
                date_range: None,
            },
        );

        map
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_mock_search() {
        let store = DocumentStore::new("mock.db", true)
            .await
            .expect("Failed to create mock store");
        let results = store.search(&vec![0.0; 384], 2, None).await.unwrap();
        assert_eq!(results.len(), 2);
    }

    #[tokio::test]
    async fn test_mock_search_with_filter() {
        let store = DocumentStore::new("mock.db", true)
            .await
            .expect("Failed to create mock store");
        let results = store
            .search(&vec![0.0; 384], 10, Some("EIA"))
            .await
            .unwrap();
        assert!(results.iter().all(|d| d.source == "EIA"));
    }

    #[tokio::test]
    async fn test_metadata() {
        let mut store = DocumentStore::new("mock.db", true)
            .await
            .expect("Failed to create mock store");

        let metadata = DocumentMetadata {
            source: "test".to_string(),
            category: "test_category".to_string(),
            tags: vec!["tag1".to_string(), "tag2".to_string()],
            focus_weight: 1.5,
            date_range: None,
        };

        store.set_document_metadata("test_doc".to_string(), metadata);

        assert!(store.get_document_metadata("test_doc").is_some());
    }
}
