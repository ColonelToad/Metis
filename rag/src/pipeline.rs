use crate::{
    document_store::DocumentStore,
    embedding::EmbeddingEngine,
    llm::LocalLLMEngine,
    template::TemplateEngine,
    types::{Explanation, TradingSignal},
};
use anyhow::Result;
use std::time::Duration;

pub struct ExplainabilityRAG {
    llm: LocalLLMEngine,
    embedder: EmbeddingEngine,
    document_store: DocumentStore,
    template_engine: TemplateEngine,
    use_fallback: bool,
}

impl ExplainabilityRAG {
    pub fn new(model_path: &str, db_path: &str, mock_mode: bool) -> Result<Self> {
        Ok(Self {
            llm: LocalLLMEngine::new(model_path, mock_mode)?,
            embedder: EmbeddingEngine::new(mock_mode)?,
            document_store: DocumentStore::new(db_path, mock_mode)?,
            template_engine: TemplateEngine::new(),
            use_fallback: false,
        })
    }

    pub async fn explain_signal(&self, signal: &TradingSignal) -> Result<Explanation> {
        // Try LLM-based explanation first
        if !self.use_fallback {
            match tokio::time::timeout(Duration::from_secs(15), self.explain_with_llm(signal)).await
            {
                Ok(Ok(explanation)) => return Ok(explanation),
                Ok(Err(e)) => {
                    eprintln!("LLM explanation failed: {}, falling back to template", e);
                }
                Err(_) => {
                    eprintln!("LLM explanation timeout, falling back to template");
                }
            }
        }

        // Fallback to template
        Ok(self.template_engine.generate(signal))
    }

    async fn explain_with_llm(&self, signal: &TradingSignal) -> Result<Explanation> {
        // 1. Build query
        let query = self.build_query(signal);

        // 2. Retrieve relevant documents
        let query_embedding = self.embedder.embed(&query).await?;
        let docs = self.document_store.search(&query_embedding, 5).await?;

        // 3. Build CoT prompt
        let prompt = self.build_cot_prompt(signal, &docs);

        // 4. Generate explanation
        let raw_text = self.llm.generate(&prompt, 512).await?;

        // 5. Parse and return
        Ok(Explanation {
            signal_id: signal.id.clone(),
            market_analysis: Some(raw_text.clone()),
            signal_drivers: None,
            risks: None,
            expected_outcome: None,
            citations: vec![],
            raw_text,
            confidence_score: 0.85,
            generated_at: chrono::Utc::now(),
        })
    }

    fn build_query(&self, signal: &TradingSignal) -> String {
        format!(
            "natural gas {} prediction grid stress {} weather anomaly {} policy events {}",
            signal.instrument,
            signal.context.grid_stress_index,
            signal.context.temperature_anomaly,
            signal.context.recent_policy_events.join(" ")
        )
    }

    fn build_cot_prompt(&self, signal: &TradingSignal, docs: &[crate::types::Document]) -> String {
        let evidence = docs
            .iter()
            .enumerate()
            .map(|(i, doc)| {
                format!(
                    "[Doc {}] {} ({})\n{}",
                    i + 1,
                    doc.title,
                    doc.source,
                    doc.content.chars().take(300).collect::<String>()
                )
            })
            .collect::<Vec<_>>()
            .join("\n\n");

        format!(
            r#"<|begin_of_text|><|start_header_id|>system<|end_header_id|>

You are an expert quantitative analyst explaining trading decisions. Use step-by-step reasoning with citations.

<|eot_id|><|start_header_id|>user<|end_header_id|>

# Trading Signal
- Instrument: {}
- Action: {}
- Confidence: {:.2}
- Timestamp: {}

# Market Context
- Current Price: ${:.2}
- Grid Stress: {:.0}/100
- Weather Anomaly: {:.1}°F above normal
- Recent Policy Events: {}

# Retrieved Evidence
{}

# Task
Explain why this trade was recommended using chain-of-thought reasoning:

1. **Market Condition Analysis**: What is the current state of the market?
2. **Signal Drivers**: What factors triggered this signal?
3. **Risk Factors**: What could go wrong with this trade?
4. **Expected Outcome**: What do we expect to happen and why?

Cite evidence using [Doc N] format. Be concise but thorough.

<|eot_id|><|start_header_id|>assistant<|end_header_id|>

Let me analyze this trade step-by-step:
"#,
            signal.instrument,
            signal.direction,
            signal.confidence,
            signal.timestamp.format("%Y-%m-%d %H:%M:%S UTC"),
            signal.context.current_price,
            signal.context.grid_stress_index,
            signal.context.temperature_anomaly,
            signal.context.recent_policy_events.join(", "),
            evidence
        )
    }
}
