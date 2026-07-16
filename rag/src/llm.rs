use anyhow::anyhow;
use pyo3::prelude::*;
use std::path::Path;

/// LLM inference engine using Python backend (via PyO3)
/// Avoids C++ compilation issues by delegating to Python's llama inference
pub struct LocalLLMEngine {
    model_path: String,
    mock_mode: bool,
}

impl LocalLLMEngine {
    pub fn new(model_path: impl AsRef<Path>, mock_mode: bool) -> anyhow::Result<Self> {
        let model_path = model_path.as_ref().to_string_lossy().to_string();

        if !mock_mode && !Path::new(&model_path).exists() {
            anyhow::bail!("Model file not found: {}", model_path);
        }

        Ok(Self {
            model_path,
            mock_mode,
        })
    }

    pub async fn generate(&self, prompt: &str, max_tokens: usize) -> anyhow::Result<String> {
        if self.mock_mode {
            return Ok(self.mock_generate(prompt));
        }

        let prompt = prompt.to_string();
        let model_path = self.model_path.clone();

        // Run inference in a blocking task via Python
        tokio::task::spawn_blocking(move || {
            Python::with_gil(|py| {
                crate::python_env::setup_sys_path(py);

                // Escape quotes and newlines for Python string literal
                let escaped_prompt = prompt
                    .replace('\\', "\\\\")
                    .replace('"', "\\\"")
                    .replace('\n', "\\n")
                    .replace('\r', "\\r")
                    .replace('\t', "\\t");

                let model_path_escaped = model_path.replace('\\', "\\\\").replace('"', "\\\"");

                let code = format!(
                    r#"
import os
import warnings

# 1. SILENCE WARNINGS BEFORE ANYTHING LOADS
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
warnings.filterwarnings('ignore')

try:
    from llama_cpp import Llama
    llm = Llama(model_path="{}", n_ctx=2048, n_gpu_layers=-1, verbose=False)
    output = llm("{}", max_tokens={}, temperature=0.7)
    __llm_output__ = output["choices"][0]["text"]
except Exception as e:
    import traceback
    traceback.print_exc()
    raise Exception(f"LLM generation failed (llama-cpp-python): {{str(e)}}")
"#,
                    model_path_escaped, escaped_prompt, max_tokens
                );

                // Execute the inference code
                py.run_bound(&code, None, None)
                    .map_err(|e| anyhow!("LLM execution failed: {}", e))?;

                // Extract the output
                let output = py
                    .eval_bound("__llm_output__", None, None)
                    .map_err(|e| anyhow!("Output extraction failed: {}", e))?
                    .extract::<String>()
                    .map_err(|e| anyhow!("Failed to extract LLM output: {}", e))?;

                Ok(output)
            })
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
