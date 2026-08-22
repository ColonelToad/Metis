//! Smoke test for the native llama.cpp LLM engine.
//!
//! Usage (from rag/): cargo run --release --example llm_smoke -- [path-to-gguf]

use std::time::Instant;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let path = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "llm/DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf".to_string());

    println!("loading engine with model: {path}");
    let t_load = Instant::now();
    let engine = rag::llm::LocalLLMEngine::new(&path, false)?;
    println!("engine started in {:.1}s", t_load.elapsed().as_secs_f64());

    let prompt = "<|im_start|>system\nYou are a concise quantitative analyst.<|im_end|>\n\
                  <|im_start|>user\nIn one sentence, why does cold weather push natural gas \
                  prices up?<|im_end|>\n<|im_start|>assistant\n";

    let t0 = Instant::now();
    let out = engine.generate(prompt, 128).await?;
    println!(
        "\n=== call 1 ({:.1}s, includes warm context reuse) ===\n{}",
        t0.elapsed().as_secs_f64(),
        out
    );

    let t1 = Instant::now();
    let out2 = engine.generate(prompt, 128).await?;
    println!(
        "\n=== call 2 ({:.1}s) ===\n{}",
        t1.elapsed().as_secs_f64(),
        out2
    );

    Ok(())
}
