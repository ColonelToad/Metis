use crate::python_bridge::PythonRAGBridge;
use crate::types::Document;
use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;

/// Metadata for documents to support filtering and scoping
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentMetadata {
    pub source: String,                    // "Congress", "EIA", "Weather", etc.
    pub category: String,                  // "policy", "market_data", "weather", etc.
    pub tags: Vec<String>,                 // User-defined tags for scoping
    pub focus_weight: f64,                 // 1.0 = normal, 2.0 = boost
    pub date_range: Option<(String, String)>, // ISO 8601 date strings
}

/// Document store wrapper around Python LanceDB
pub struct DocumentStore {
    db_path: PathBuf,
    mock_mode: bool,
    bridge: Option<PythonRAGBridge>,
    mock_documents: Vec<Document>,
    metadata_index: HashMap<String, DocumentMetadata>,
}

impl DocumentStore {
    /// Initialize document store
    pub async fn new(db_path: impl Into<PathBuf>, mock_mode: bool) -> Result<Self> {
        let db_path = db_path.into();

        let (bridge, mock_documents, metadata_index) = if mock_mode {
            (None, Self::create_mock_documents(), HashMap::new())
        } else {
            // Initialize Python bridge for real mode
            let bridge = PythonRAGBridge::new()?;
            let metadata = Self::create_mock_metadata();
            (Some(bridge), vec![], metadata)
        };

        Ok(Self {
            db_path,
            mock_mode,
            bridge,
            mock_documents,
            metadata_index,
        })
    }

    /// Search for documents using vector similarity
    /// Input: query embedding, top_k results, optional source filter
    /// Output: ranked list of documents
    pub async fn search(
        &self,
        query_embedding: &[f32],
        top_k: usize,
        source_filter: Option<&str>,
    ) -> Result<Vec<Document>> {
        if self.mock_mode {
            // Mock: return documents matching source filter if provided
            let mut results = self.mock_documents.clone();
            if let Some(source) = source_filter {
                results.retain(|d| d.source == source);
            }
            return Ok(results.into_iter().take(top_k).collect());
        }

        if let Some(bridge) = &self.bridge {
            bridge
                .retrieve_documents(query_embedding, top_k, source_filter)
                .await
        } else {
            Ok(vec![])
        }
    }

    /// Index documents into the store
    pub async fn index_documents(&mut self, docs: Vec<Document>) -> Result<usize> {
        if self.mock_mode {
            self.mock_documents.extend(docs.clone());
            return Ok(docs.len());
        }

        if let Some(bridge) = &self.bridge {
            bridge.index_documents(docs).await
        } else {
            Ok(0)
        }
    }

    /// Set metadata for a document (for filtering/scoping)
    pub fn set_document_metadata(&mut self, doc_id: String, metadata: DocumentMetadata) {
        self.metadata_index.insert(doc_id, metadata);
    }

    /// Get metadata for a document
    pub fn get_document_metadata(&self, doc_id: &str) -> Option<&DocumentMetadata> {
        self.metadata_index.get(doc_id)
    }

    /// Get all documents with a specific tag
    pub fn documents_by_tag(&self, tag: &str) -> Vec<&DocumentMetadata> {
        self.metadata_index
            .values()
            .filter(|m| m.tags.contains(&tag.to_string()))
            .collect()
    }

    /// Health check: verify store is accessible
    pub async fn health_check(&self) -> Result<bool> {
        if self.mock_mode {
            return Ok(true);
        }

        if let Some(bridge) = &self.bridge {
            bridge.health_check()
        } else {
            Ok(false)
        }
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
