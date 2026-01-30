use anyhow::Result;

pub struct EmbeddingEngine {
    mock_mode: bool,
    dimension: usize,
}

impl EmbeddingEngine {
    pub fn new(mock_mode: bool) -> Result<Self> {
        Ok(Self {
            mock_mode,
            dimension: 384, // BGE-small dimension
        })
    }

    pub async fn embed(&self, text: &str) -> Result<Vec<f32>> {
        if self.mock_mode {
            return Ok(self.mock_embed(text));
        }

        // TODO: Implement fastembed or sentence-transformers via PyO3
        let text = text.to_string();
        tokio::task::spawn_blocking(move || {
            // In production: call embedding model
            let _ = text;
            Ok(vec![0.0; 384])
        })
        .await?
    }

    pub async fn embed_batch(&self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        let mut embeddings = Vec::new();
        for text in texts {
            embeddings.push(self.embed(text).await?);
        }
        Ok(embeddings)
    }

    fn mock_embed(&self, text: &str) -> Vec<f32> {
        // Deterministic mock embedding based on text hash
        let hash = text.chars().map(|c| c as u32).sum::<u32>();
        let mut embedding = vec![0.0; self.dimension];
        for i in 0..self.dimension {
            embedding[i] = ((hash + i as u32) % 100) as f32 / 100.0;
        }
        embedding
    }

    pub fn dimension(&self) -> usize {
        self.dimension
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_mock_embedding() {
        let embedder = EmbeddingEngine::new(true).unwrap();
        let embedding = embedder.embed("test query").await.unwrap();
        assert_eq!(embedding.len(), 384);
    }
}
