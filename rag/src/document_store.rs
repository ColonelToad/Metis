use crate::types::Document;
use anyhow::Result;
use std::path::PathBuf;

pub struct DocumentStore {
    #[allow(dead_code)]
    db_path: PathBuf,
    mock_mode: bool,
    mock_documents: Vec<Document>,
}

impl DocumentStore {
    pub fn new(db_path: impl Into<PathBuf>, mock_mode: bool) -> Result<Self> {
        let db_path = db_path.into();

        let mock_documents = if mock_mode {
            Self::create_mock_documents()
        } else {
            vec![]
        };

        Ok(Self {
            db_path,
            mock_mode,
            mock_documents,
        })
    }

    pub async fn search(&self, query_embedding: &[f32], top_k: usize) -> Result<Vec<Document>> {
        if self.mock_mode {
            let _ = query_embedding;
            return Ok(self.mock_documents.iter().take(top_k).cloned().collect());
        }

        // TODO: Implement LanceDB search
        Ok(vec![])
    }

    pub async fn upsert(&mut self, doc: Document) -> Result<()> {
        if self.mock_mode {
            self.mock_documents.push(doc);
            return Ok(());
        }

        // TODO: Implement LanceDB upsert
        Ok(())
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
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_mock_search() {
        let store = DocumentStore::new("mock.db", true).unwrap();
        let results = store.search(&vec![0.0; 384], 2).await.unwrap();
        assert_eq!(results.len(), 2);
    }
}
