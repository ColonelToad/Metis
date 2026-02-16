use chrono::Utc;
use rag::pipeline::ExplainabilityRAG;
use rag::types::{TradingContext, TradingSignal};

#[tokio::main]
async fn main() {
    println!("=== RAG System Test ===\n");

    // Example trading signal
    let signal = TradingSignal {
        id: "sig1".to_string(),
        instrument: "NG".to_string(),
        direction: "BUY".to_string(),
        confidence: 0.82,
        timestamp: Utc::now(),
        context: TradingContext {
            current_price: 2.85,
            grid_stress_index: 75.0,
            temperature_anomaly: 8.5,
            recent_policy_events: vec!["FERC Order 2023-45".to_string()],
            primary_region: "South-Central".to_string(),
        },
    };

    // Set mock_mode to false to use real LLM
    let mock_mode = false;

    println!("Initializing RAG pipeline (mock_mode: {})...", mock_mode);
    let rag = ExplainabilityRAG::new(
        "./llm/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
        "mock.db",
        mock_mode,
    )
    .await
    .expect("Failed to initialize RAG pipeline");

    println!("Generating explanation...\n");
    let result = rag.explain_signal(&signal).await;

    match result {
        rag::pipeline::ExplanationResult::Success { explanation } => {
            println!("--- EXPLANATION (Success) ---");
            println!("{}", explanation.raw_text);
            println!("\n--- METADATA ---");
            println!("Signal ID: {}", explanation.signal_id);
            println!("Confidence: {:.2}", explanation.confidence_score);
            println!("Generated at: {}", explanation.generated_at);
        }
        rag::pipeline::ExplanationResult::Timeout { partial_explanation, .. } => {
            println!("--- EXPLANATION (Timeout) ---");
            if let Some(explanation) = partial_explanation {
                println!("{}", explanation.raw_text);
                println!("\n--- METADATA ---");
                println!("Signal ID: {}", explanation.signal_id);
                println!("Confidence: {:.2}", explanation.confidence_score);
            }
        }
        rag::pipeline::ExplanationResult::MissingDocuments { explanation, missing_docs } => {
            println!("--- EXPLANATION (Partial - Missing Docs) ---");
            println!("{}", explanation.raw_text);
            println!("\nMissing documents: {:?}", missing_docs);
        }
        rag::pipeline::ExplanationResult::TemplateFallback { explanation, reason } => {
            println!("--- EXPLANATION (Fallback: {}) ---", reason);
            println!("{}", explanation.raw_text);
        }
    }
}
