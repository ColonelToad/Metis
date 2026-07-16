//! Text embedding via a native, local ONNX model (fastembed/ort), rather
//! than the Python/PyO3 bridge.
//!
//! Previously this called `PythonRAGBridge::embed_text`, which builds and
//! executes Python source as a string on every call, going through the
//! bridge's single dedicated GIL-owning thread. Embedding is the most
//! frequently-called operation in the RAG pipeline — every retrieval query
//! re-embeds — which made it the most frequently-crossed PyO3/GIL boundary
//! in the system. all-MiniLM-L6-v2 has an official pre-exported ONNX build
//! and is one of fastembed's default supported models, so unlike full LLM
//! generation (which still needs Python — see llm.rs), this doesn't need
//! the boundary at all.
//!
//! One consequence worth knowing, not hiding: after this swap, nothing in
//! this crate calls `PythonRAGBridge::embed_text` anymore. If nothing else
//! picks it up, that dedicated-thread/GIL-ownership machinery in
//! `python_bridge.rs` has no live caller left — worth a deliberate decision
//! (keep for future PyO3 needs, or retire it) rather than leaving it
//! looking load-bearing when it isn't.
//!
//! `fastembed`'s `embed()` is synchronous and CPU-bound (ONNX inference, no
//! Tokio inside it) — calls are dispatched via `spawn_blocking` rather than
//! called directly from async code, since calling blocking work on an async
//! worker thread is exactly the footgun flagged elsewhere in this codebase
//! (`ais_vessel_tracking`'s std `Mutex` inside an `async fn`).
//!
//! First run downloads the ONNX model to `.fastembed_cache/` (needs network
//! once); subsequent runs load from that cache offline. `new()` is
//! synchronous, so that first download blocks whatever thread constructs
//! this — a one-time cost per process lifetime, not per request, but worth
//! knowing if this is ever constructed from inside an async context.

use anyhow::{anyhow, Result};
use fastembed::{EmbeddingModel, TextEmbedding, TextInitOptions};
use std::sync::{Arc, Mutex};

pub struct EmbeddingEngine {
    mock_mode: bool,
    model: Option<Arc<Mutex<TextEmbedding>>>,
    dimension: usize,
}

impl EmbeddingEngine {
    pub fn new(mock_mode: bool) -> Result<Self> {
        let model = if mock_mode {
            None
        } else {
            let text_embedding = TextEmbedding::try_new(
                TextInitOptions::new(EmbeddingModel::AllMiniLML6V2)
                    .with_show_download_progress(true),
            )
            .map_err(|e| anyhow!("Failed to load embedding model: {}", e))?;
            Some(Arc::new(Mutex::new(text_embedding)))
        };

        Ok(Self {
            mock_mode,
            model,
            dimension: 384, // all-MiniLM-L6-v2 dimension
        })
    }

    /// Embed a single text string.
    pub async fn embed(&self, text: &str) -> Result<Vec<f32>> {
        if self.mock_mode {
            return Ok(self.mock_embed(text));
        }
        let texts = vec![text.to_string()];
        let mut batch = self.embed_batch(&texts).await?;
        batch
            .pop()
            .ok_or_else(|| anyhow!("Embedding model returned no output for input text"))
    }

    /// Embed multiple texts in one native batch call, rather than looping
    /// one `embed()` call at a time — the old PyO3-bridge-backed version had
    /// to loop because each call meant a full round trip through generated
    /// Python source; the native model can batch for real.
    pub async fn embed_batch(&self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        if self.mock_mode {
            return Ok(texts.iter().map(|t| self.mock_embed(t)).collect());
        }

        let model = self.model.clone().ok_or_else(|| {
            anyhow!("Embedding model not initialized (mock_mode is false but no model loaded)")
        })?;
        let texts = texts.to_vec();

        tokio::task::spawn_blocking(move || {
            let mut model = model
                .lock()
                .map_err(|_| anyhow!("Embedding model mutex poisoned"))?;
            model
                .embed(texts, None)
                .map_err(|e| anyhow!("Embedding inference failed: {}", e))
        })
        .await
        .map_err(|e| anyhow!("Embedding task panicked: {}", e))?
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

    #[tokio::test]
    async fn test_mock_embed_batch_matches_single_calls() {
        let embedder = EmbeddingEngine::new(true).unwrap();
        let batch = embedder
            .embed_batch(&["a".to_string(), "b".to_string()])
            .await
            .unwrap();
        assert_eq!(batch.len(), 2);
        assert_eq!(batch[0], embedder.embed("a").await.unwrap());
    }
}
