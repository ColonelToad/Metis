use crate::python_bridge::PythonRAGBridge;
use anyhow::Result;

pub struct EmbeddingEngine {
    bridge: Option<PythonRAGBridge>,
    dimension: usize,
}

impl EmbeddingEngine {
    pub fn new(mock_mode: bool) -> Result<Self> {
        let bridge = if mock_mode {
            None
        } else {
            Some(PythonRAGBridge::new()?)
        };

        Ok(Self {
            bridge,
            dimension: 384, // sentence-transformers all-MiniLM-L6-v2 dimension
        })
    }

    /// Embed a single text string using sentence-transformers
    pub async fn embed(&self, text: &str) -> Result<Vec<f32>> {
        if let Some(bridge) = &self.bridge {
            bridge.embed_text(text).await
        } else {
            // Mock mode: return deterministic vector
            Ok(self.mock_embed(text))
        }
    }

    /// Embed multiple texts in batch (parallel processing)
    pub async fn embed_batch(&self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        let mut embeddings = Vec::new();
        for text in texts {
            embeddings.push(self.embed(text).await?);
        }
        Ok(embeddings)
    }

    /// Get embedding dimension (for vector store initialization)
    pub fn dimension(&self) -> usize {
        self.dimension
    }

    fn mock_embed(&self, text: &str) -> Vec<f32> {
        // Deterministic mock embedding based on text hash
        let hash = text.chars().map(|c| c as u32).sum::<u32>();
        let mut embedding = vec![0.0; self.dimension];
        for (i, val) in embedding.iter_mut().enumerate().take(self.dimension) {
            *val = ((hash + i as u32) % 100) as f32 / 100.0;
        }
        embedding
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_mock_embedding() {
        let embedder = EmbeddingEngine::new(true).unwrap();
        let embedding = embedder.embed("test text").await.unwrap();
        assert_eq!(embedding.len(), 384);
    }
}
