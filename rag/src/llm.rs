//! Native LLM inference over llama.cpp bindings (`llama-cpp-2`).
//!
//! Replaces the previous PyO3 → llama-cpp-python delegation, which reloaded
//! the ~4.7 GB GGUF from disk on every call and serialized all inference
//! behind the GIL.
//!
//! `LlamaBackend` is !Send/!Sync, so the backend, loaded model and a warm
//! `LlamaContext` live on a dedicated worker thread for the lifetime of the
//! engine. Generation requests are sent over a bounded channel and replies
//! come back through a tokio oneshot; the single worker also serializes
//! GPU/CPU-heavy decoding naturally.

use anyhow::{anyhow, bail};
use llama_cpp_2::context::params::LlamaContextParams;
use llama_cpp_2::llama_backend::LlamaBackend;
use llama_cpp_2::llama_batch::LlamaBatch;
use llama_cpp_2::model::params::LlamaModelParams;
use llama_cpp_2::model::{AddBos, LlamaModel};
use llama_cpp_2::sampling::LlamaSampler;
use llama_cpp_2::{send_logs_to_tracing, LogOptions};
use std::num::NonZeroU32;
use std::path::Path;
use std::sync::mpsc;
use std::time::{SystemTime, UNIX_EPOCH};

const N_CTX: u32 = 4096;
const TEMPERATURE: f32 = 0.7;
const TOP_P: f32 = 0.95;

/// ChatML / DeepSeek turn terminators. Any of these ends generation early
/// (the tokenizer's EOG token is checked as well).
const STOP_MARKERS: &[&str] = &["<|im_end|>", "<|im_start|>", "<｜end▁of▁sentence｜>"];

enum LlmJob {
    Generate {
        prompt: String,
        max_tokens: usize,
        seed: u32,
        reply: tokio::sync::oneshot::Sender<anyhow::Result<String>>,
    },
}

pub struct LocalLLMEngine {
    mock_mode: bool,
    tx: Option<mpsc::SyncSender<LlmJob>>,
}

impl LocalLLMEngine {
    pub fn new(model_path: impl AsRef<Path>, mock_mode: bool) -> anyhow::Result<Self> {
        if mock_mode {
            return Ok(Self {
                mock_mode,
                tx: None,
            });
        }

        let path = model_path.as_ref();
        if !path.exists() {
            bail!("Model file not found: {}", path.display());
        }

        let tx = spawn_worker(path.to_string_lossy().into_owned())?;
        Ok(Self {
            mock_mode: false,
            tx: Some(tx),
        })
    }

    pub async fn generate(&self, prompt: &str, max_tokens: usize) -> anyhow::Result<String> {
        if self.mock_mode {
            return Ok(self.mock_generate(prompt));
        }

        let tx = self
            .tx
            .as_ref()
            .ok_or_else(|| anyhow!("LLM worker is not running"))?;

        let (reply_tx, reply_rx) = tokio::sync::oneshot::channel();
        let seed = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .subsec_nanos();

        tx.send(LlmJob::Generate {
            prompt: prompt.to_string(),
            max_tokens,
            seed,
            reply: reply_tx,
        })
        .map_err(|_| anyhow!("LLM worker has shut down"))?;

        reply_rx
            .await
            .map_err(|_| anyhow!("LLM worker dropped the reply channel"))?
    }

    fn mock_generate(&self, _prompt: &str) -> String {
        r#"Let me analyze this trade step-by-step:

## 1. Market Condition Analysis
The natural gas market is currently experiencing elevated stress levels. Grid stress index at 75/100 indicates high demand periods, likely driven by weather conditions [Doc 1]. Current price levels suggest supply constraints in key delivery regions.

## 2. Signal Drivers
This BUY signal was triggered by:
- **Weather anomaly**: 8.5°F above seasonal average, driving cooling demand [Doc 2]
- **Grid stress**: Regional transmission congestion limiting supply flexibility
- **Policy context**: Recent FERC order on pipeline capacity may constrain deliveries [Doc 3]

## 3. Risk Factors
Key risks to monitor:
- Weather normalization could reduce demand pressure
- Potential for increased LNG export constraints
- Regulatory uncertainty around pipeline expansions

## 4. Expected Outcome
Based on the confluence of supply constraints and elevated demand, we expect prices to move 3-5% higher over the next 5-7 trading days. The grid stress metric historically correlates with 0.72 accuracy to short-term price movements [Doc 1]."#.to_string()
    }
}

fn spawn_worker(model_path: String) -> anyhow::Result<mpsc::SyncSender<LlmJob>> {
    let (tx, rx) = mpsc::sync_channel::<LlmJob>(8);

    let handle = std::thread::Builder::new()
        .name("metis-llm-worker".to_string())
        .stack_size(64 * 1024 * 1024)
        .spawn(move || {
            if let Err(e) = worker_loop(rx, &model_path) {
                tracing::error!("LLM worker terminated: {e:#}");
            }
        })?;

    std::mem::forget(handle);
    Ok(tx)
}

fn worker_loop(rx: mpsc::Receiver<LlmJob>, model_path: &str) -> anyhow::Result<()> {
    send_logs_to_tracing(LogOptions::default().with_logs_enabled(false));

    let backend = LlamaBackend::init()?;

    let model_params = LlamaModelParams::default();
    let model_params = std::pin::pin!(model_params);
    let model = LlamaModel::load_from_file(&backend, Path::new(model_path), &model_params)
        .map_err(|e| anyhow!("failed to load GGUF {}: {}", model_path, e))?;

    // Hybrid Intel CPUs (P/E cores): generation synchronizes all threads per
    // token, so E-cores throttle P-cores. Default to 4 (P-core threads on the
    // target machine); override with METIS_LLM_THREADS.
    let threads = std::env::var("METIS_LLM_THREADS")
        .ok()
        .and_then(|v| v.parse::<i32>().ok())
        .unwrap_or(4);

    let ctx_params = LlamaContextParams::default()
        .with_n_ctx(NonZeroU32::new(N_CTX))
        .with_n_threads(threads)
        .with_n_threads_batch(threads);

    let mut ctx = model
        .new_context(&backend, ctx_params)
        .map_err(|e| anyhow!("failed to create inference context: {}", e))?;

    tracing::info!(
        "LLM worker ready: model={}, n_ctx={}, threads={}",
        model_path,
        N_CTX,
        threads
    );

    while let Ok(job) = rx.recv() {
        match job {
            LlmJob::Generate {
                prompt,
                max_tokens,
                seed,
                reply,
            } => {
                let result = generate_inner(&model, &mut ctx, &prompt, max_tokens, seed);
                let _ = reply.send(result);
            }
        }
    }

    Ok(())
}

fn generate_inner(
    model: &LlamaModel,
    ctx: &mut llama_cpp_2::context::LlamaContext<'_>,
    prompt: &str,
    max_tokens: usize,
    seed: u32,
) -> anyhow::Result<String> {
    let tokens = model
        .str_to_token(prompt, AddBos::Always)
        .map_err(|e| anyhow!("failed to tokenize prompt: {}", e))?;

    if tokens.is_empty() {
        bail!("prompt tokenized to zero tokens");
    }
    if tokens.len() + 2 >= N_CTX as usize {
        bail!(
            "prompt too long: {} tokens exceeds context budget {}",
            tokens.len(),
            N_CTX
        );
    }
    let budget = max_tokens.min(N_CTX as usize - tokens.len() - 1).max(1);

    let mut batch = LlamaBatch::new(tokens.len(), 1);
    let last_index = (tokens.len() - 1) as i32;
    for (i, token) in (0_i32..).zip(tokens.iter()) {
        batch.add(*token, i, &[0], i == last_index)?;
    }
    ctx.decode(&mut batch)
        .map_err(|e| anyhow!("prefill decode failed: {}", e))?;

    let mut sampler = LlamaSampler::chain_simple([
        LlamaSampler::temp(TEMPERATURE),
        LlamaSampler::top_p(TOP_P, 1),
        LlamaSampler::dist(seed),
    ]);

    let mut decoder = encoding_rs::UTF_8.new_decoder();
    let mut output = String::new();
    let mut n_cur = batch.n_tokens();
    let mut generated = 0usize;

    while generated < budget {
        let token = sampler.sample(ctx, batch.n_tokens() - 1);
        sampler.accept(token);

        if model.is_eog_token(token) {
            break;
        }

        let piece = model
            .token_to_piece(token, &mut decoder, true, None)
            .map_err(|e| anyhow!("failed to detokenize: {}", e))?;
        output.push_str(&piece);
        generated += 1;

        if let Some(cut) = STOP_MARKERS.iter().find_map(|m| output.find(m)) {
            output.truncate(cut);
            break;
        }

        batch.clear();
        batch.add(token, n_cur, &[0], true)?;
        n_cur += 1;

        ctx.decode(&mut batch)
            .map_err(|e| anyhow!("decode failed at token {}: {}", generated, e))?;
    }

    ctx.clear_kv_cache();
    Ok(output.trim().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_mock_llm() {
        let llm = LocalLLMEngine::new("mock.gguf", true).unwrap();
        let response = llm.generate("test prompt", 512).await.unwrap();
        assert!(!response.is_empty());
        assert!(response.contains("Market Condition Analysis"));
    }
}
