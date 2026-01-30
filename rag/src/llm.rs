use anyhow::{Context, Result};
use llama_cpp_2::model::Special;
use llama_cpp_2::sampling::LlamaSampler;
use llama_cpp_2::{
    context::params::LlamaContextParams,
    llama_backend::LlamaBackend,
    llama_batch::LlamaBatch,
    model::{params::LlamaModelParams, AddBos, LlamaModel},
};
use std::num::NonZeroU32;
use std::path::Path;
use std::sync::Arc;

pub struct LocalLLMEngine {
    #[allow(dead_code)]
    model_path: String,
    mock_mode: bool,
    backend: Option<Arc<LlamaBackend>>,
    model: Option<Arc<LlamaModel>>,
}

impl LocalLLMEngine {
    pub fn new(model_path: impl AsRef<Path>, mock_mode: bool) -> Result<Self> {
        let model_path = model_path.as_ref().to_string_lossy().to_string();

        if !mock_mode && !Path::new(&model_path).exists() {
            anyhow::bail!("Model file not found: {}", model_path);
        }

        let (backend, model) = if !mock_mode {
            // Initialize backend
            let backend = LlamaBackend::init().context("Failed to initialize LlamaBackend")?;

            // Load model
            let model_params = LlamaModelParams::default();
            let model = LlamaModel::load_from_file(&backend, &model_path, &model_params)
                .context("Failed to load Llama model")?;

            (Some(Arc::new(backend)), Some(Arc::new(model)))
        } else {
            (None, None)
        };

        Ok(Self {
            model_path,
            mock_mode,
            backend,
            model,
        })
    }

    pub async fn generate(&self, prompt: &str, max_tokens: usize) -> Result<String> {
        if self.mock_mode {
            return Ok(self.mock_generate(prompt));
        }

        let model = Arc::clone(self.model.as_ref().context("Model not loaded")?);
        let backend = Arc::clone(self.backend.as_ref().context("Backend not loaded")?);
        let prompt = prompt.to_string();

        // Run inference in a blocking task
        tokio::task::spawn_blocking(move || {
            // Create context
            let ctx_params = LlamaContextParams::default().with_n_ctx(NonZeroU32::new(2048));

            let mut ctx = model
                .new_context(&backend, ctx_params)
                .context("Failed to create context")?;

            // Tokenize the prompt
            let tokens = model
                .str_to_token(&prompt, AddBos::Always)
                .context("Failed to tokenize prompt")?;

            // Create batch and add tokens
            let mut batch = LlamaBatch::new(512, 1);

            for (i, &token) in tokens.iter().enumerate() {
                let is_last = i == tokens.len() - 1;
                batch
                    .add(token, i as i32, &[0], is_last)
                    .context("Failed to add token to batch")?;
            }

            // Decode the batch
            ctx.decode(&mut batch).context("Failed to decode batch")?;

            // Create a greedy sampler
            let mut sampler = LlamaSampler::greedy();

            // Generate tokens
            let mut output = String::new();
            let mut n_cur = tokens.len();

            for _ in 0..max_tokens {
                // Sample next token
                let new_token_id = sampler.sample(&ctx, batch.n_tokens() - 1);

                // Check for EOS
                if model.is_eog_token(new_token_id) {
                    break;
                }

                // Decode token to string
                let token_str = model
                    .token_to_str(new_token_id, Special::Tokenize)
                    .context("Failed to decode token")?;

                output.push_str(&token_str);

                // Prepare for next iteration
                batch.clear();
                batch
                    .add(new_token_id, n_cur as i32, &[0], true)
                    .context("Failed to add token to batch")?;

                ctx.decode(&mut batch).context("Failed to decode batch")?;

                n_cur += 1;
            }

            Ok(output)
        })
        .await?
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
