use rag::pipeline::{ExplainabilityRAG, ExplanationResult};
use rag::types::{TradingContext, TradingSignal};
use std::path::Path;
use std::time::Instant;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize logging
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::INFO)
        .init();

    println!("\n╔════════════════════════════════════════════════════════╗");
    println!("║     METIS RAG PIPELINE - SIGNAL EXPLANATION TEST      ║");
    println!("╚════════════════════════════════════════════════════════╝\n");

    // Paths to model and database (relative to rag/ manifest dir)
    let model_path = "llm/DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf";
    let db_path = "C:\\Users\\legot\\Metis\\data\\lance";

    // Check if model file exists
    if !Path::new(model_path).exists() {
        println!("  WARNING: Model file not found at {}", model_path);
        println!("   The test will run in mock mode (no actual LLM inference)");
        println!("   To use real inference, download the DeepSeek model first.\n");
    }

    // Check if database exists
    let has_docs = Path::new(db_path).exists();
    if !has_docs {
        println!("  WARNING: LanceDB not found at {}", db_path);
        println!("   The test will run with mock documents (empty retrieval)");
        println!("   To test with real documents, run the ingestion pipelines first.\n");
    }

    // Create a realistic trading signal
    let signal = TradingSignal {
        id: "ng_long_20260706_001".to_string(),
        instrument: "NG".to_string(),
        direction: "LONG".to_string(),
        confidence: 0.78,
        timestamp: chrono::Utc::now(),
        context: TradingContext {
            current_price: 3.45,
            grid_stress_index: 78.0,
            temperature_anomaly: 8.5, // 8.5°F above seasonal average
            recent_policy_events: vec![
                "FERC Order 902-B on pipeline capacity".to_string(),
                "NERC cold weather alert".to_string(),
            ],
            primary_region: "ERCOT".to_string(),
        },
    };

    println!("SIGNAL DETAILS");
    println!("  ID:                 {}", signal.id);
    println!("  Instrument:         {}", signal.instrument);
    println!("  Direction:          {}", signal.direction);
    println!("  Confidence:         {:.1}%", signal.confidence * 100.0);
    println!("  Current Price:      ${:.2}", signal.context.current_price);
    println!(
        "  Grid Stress:        {:.0}/100",
        signal.context.grid_stress_index
    );
    println!(
        "  Temp Anomaly:       +{:.1}°F",
        signal.context.temperature_anomaly
    );
    println!("  Primary Region:     {}", signal.context.primary_region);
    println!(
        "  Policy Events:      {:?}\n",
        signal.context.recent_policy_events
    );

    // Initialize RAG pipeline
    // Try with real mode first, fall back to mock if needed
    let mock_mode = !Path::new(model_path).exists() || !has_docs;

    println!("INITIALIZING RAG PIPELINE");
    println!(
        "  Mode:               {}",
        if mock_mode { "MOCK" } else { "REAL" }
    );
    println!("  Model:              {}", model_path);
    println!("  Database:           {}\n", db_path);

    let init_start = Instant::now();
    let rag = match ExplainabilityRAG::new(model_path, db_path, mock_mode).await {
        Ok(rag) => {
            let elapsed = init_start.elapsed();
            println!("RAG initialized in {:.2}s\n", elapsed.as_secs_f64());
            rag
        }
        Err(e) => {
            eprintln!("Failed to initialize RAG: {}", e);
            return Err(e);
        }
    };

    // Generate explanation
    println!("GENERATING EXPLANATION");
    println!("  Starting multi-hop reasoning chain...\n");

    let start = Instant::now();
    let result = rag.explain_signal(&signal).await;
    let elapsed = start.elapsed();

    println!("LATENCY BREAKDOWN");
    println!("  Total:              {:.3}s", elapsed.as_secs_f64());
    println!("  Target budget:      1-5s");
    println!(
        "  Within budget:      {}\n",
        if elapsed.as_secs() <= 5 {
            "YES"
        } else {
            "NO - OPTIMIZE NEEDED"
        }
    );

    // Parse result
    match result {
        ExplanationResult::Success { explanation } => {
            println!("EXPLANATION GENERATED SUCCESSFULLY\n");

            println!("EXPLANATION SUMMARY");
            println!("  Signal ID:          {}", explanation.signal_id);
            println!(
                "  Overall Confidence: {:.1}%",
                explanation.confidence_score * 100.0
            );
            println!("  Generated At:       {}", explanation.generated_at);
            println!("  Citations:          {}\n", explanation.citations.len());

            // Print 8-step framework results
            println!("8-STEP FRAMEWORK ANALYSIS");

            if let Some(ref_class) = &explanation.reference_class {
                println!("\n Reference Class:");
                println!("      Class: {}", ref_class.class_name);
                println!("      Base Rate: {:.1}%", ref_class.base_rate * 100.0);
                println!("      Sample Size: {}", ref_class.sample_size);
            }

            if let Some(ensemble) = &explanation.ensemble {
                println!("\n Ensemble Aggregation:");
                println!("      Final Signal: {:.2}", ensemble.final_signal);
                println!("      Agreement: {:.1}%", ensemble.agreement * 100.0);
                println!("      Components: {}", ensemble.components.len());
            }

            if let Some(bayesian) = &explanation.bayesian_update {
                println!("\n Bayesian Update:");
                println!("      Prior: {:.2}", bayesian.prior);
                println!("      Likelihood Ratio: {:.2}x", bayesian.likelihood_ratio);
                println!("      Posterior: {:.2}", bayesian.posterior);
            }

            if let Some(scenarios) = &explanation.scenarios {
                println!("\n  Scenarios ({}):", scenarios.len());
                for (i, scenario) in scenarios.iter().enumerate() {
                    println!(
                        "      [{}] {} (P={:.1}%)",
                        i + 1,
                        scenario.name,
                        scenario.probability * 100.0
                    );
                }
            }

            if let Some(ev) = &explanation.expected_value {
                println!("\n  Expected Value:");
                println!("      Expected Return: {:.2}%", ev.expected_return * 100.0);
                println!("      Volatility: {:.2}%", ev.volatility * 100.0);
                println!("      Sharpe Ratio: {:.2}", ev.sharpe_ratio);
                println!(
                    "      Kelly Position: {:.2}%",
                    ev.kelly_position_size * 100.0
                );
            }

            if let Some(risk) = &explanation.risk_assessment {
                println!("\n  Risk Assessment:");
                println!("      Worst Case: {:.2}%", risk.worst_case * 100.0);
                println!(
                    "      Tail Risk Probability: {:.2}%",
                    risk.tail_risk_probability * 100.0
                );
                println!(
                    "      Concentration Risks: {}",
                    risk.concentration_risks.len()
                );
            }

            println!("\n All analysis steps completed successfully\n");
        }

        ExplanationResult::Timeout {
            partial_explanation,
            retry_token,
        } => {
            println!("  TIMEOUT - Reasoning took > 180s\n");
            println!("  Partial Explanation: {}\n", partial_explanation.is_some());
            println!("  Retry Token: {}\n", retry_token);
        }

        ExplanationResult::MissingDocuments {
            explanation,
            missing_docs,
        } => {
            println!("  PARTIAL SUCCESS - Some documents missing\n");
            println!("  Explanation Generated: Yes");
            println!("  Missing: {} documents", missing_docs.len());
            println!("  Signal ID: {}", explanation.signal_id);
            println!(
                "  Confidence: {:.1}%\n",
                explanation.confidence_score * 100.0
            );
        }

        ExplanationResult::TemplateFallback {
            explanation,
            reason,
        } => {
            println!("  FALLBACK - Using template explanation\n");
            println!("  Reason: {}", reason);
            println!("  Signal ID: {}", explanation.signal_id);
            println!(
                "  Confidence: {:.1}%\n",
                explanation.confidence_score * 100.0
            );
        }
    }

    Ok(())
}
