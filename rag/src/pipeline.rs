use crate::{
    document_scope::DocumentScope,
    document_store::DocumentStore,
    embedding::EmbeddingEngine,
    explanation_parser::ExplanationParser,
    explanation_cache::ExplanationCache,
    llm::LocalLLMEngine,
    template::TemplateEngine,
    types::{Explanation, TradingSignal, Document},
};
use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::time::Duration;
use uuid::Uuid;

/// Result type for explanation generation with different outcomes
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ExplanationResult {
    /// Successful explanation with full reasoning
    Success {
        explanation: Explanation,
    },
    /// LLM timed out but generated partial explanation
    Timeout {
        partial_explanation: Option<Explanation>,
        retry_token: String,
    },
    /// Missing documents but explanation still generated
    MissingDocuments {
        explanation: Explanation,
        missing_docs: Vec<String>,
    },
    /// Fallback to template (LLM failed completely)
    TemplateFallback {
        explanation: Explanation,
        reason: String,
    },
}

pub struct ExplainabilityRAG {
    llm: LocalLLMEngine,
    embedder: EmbeddingEngine,
    pub document_store: DocumentStore,
    template_engine: TemplateEngine,
    active_scope: DocumentScope,
    explanation_cache: ExplanationCache,
}

impl ExplainabilityRAG {
    pub async fn new(model_path: &str, db_path: &str, mock_mode: bool) -> Result<Self> {
        Ok(Self {
            llm: LocalLLMEngine::new(model_path, mock_mode)?,
            embedder: EmbeddingEngine::new(mock_mode)?,
            document_store: DocumentStore::new(db_path, mock_mode).await?,
            template_engine: TemplateEngine::new(),
            active_scope: DocumentScope::default(),
            explanation_cache: ExplanationCache::new(100), // Max 100 cached results
        })
    }

    /// Set the active document scope for retrieval
    pub fn set_scope(&mut self, scope: DocumentScope) {
        self.active_scope = scope;
    }

    /// Explain a trading signal with full error handling and fallback chain
    pub async fn explain_signal(&self, signal: &TradingSignal) -> ExplanationResult {
        // Check cache first (huge speedup if signal is similar to recent ones)
        if let Some(cached) = self.explanation_cache.get(signal).await {
            tracing::info!("Using cached explanation for signal: {}", signal.id);
            return cached;
        }

        // Try LLM-based explanation with timeout (45s to account for first-run model initialization)
        match tokio::time::timeout(
            Duration::from_secs(180),
            self.explain_with_llm(signal),
        )
        .await
        {
            // Success case
            Ok(Ok(ExplanationResult::Success { explanation })) => {
                let result = ExplanationResult::Success { explanation };
                self.explanation_cache.put(signal, result.clone()).await;
                return result;
            }

            // LLM generated output but returned error result
            Ok(Ok(other_result)) => {
                self.explanation_cache.put(signal, other_result.clone()).await;
                return other_result;
            }

            // LLM failed with error
            Ok(Err(e)) => {
                tracing::warn!("LLM explanation failed: {}, falling back to template", e);
                let result = ExplanationResult::TemplateFallback {
                    explanation: self.template_engine.generate(signal),
                    reason: format!("LLM error: {}", e),
                };
                self.explanation_cache.put(signal, result.clone()).await;
                return result;
            }

            // LLM timeout - try to generate quick template while showing timeout
            Err(_) => {
                tracing::warn!("LLM explanation timeout, showing template");
                let retry_token = Uuid::new_v4().to_string();
                let partial = Some(self.template_engine.generate(signal));

                let result = ExplanationResult::Timeout {
                    partial_explanation: partial,
                    retry_token,
                };
                // Don't cache timeouts - they're transient
                return result;
            }
        }
    }

    /// Retry explanation using the retry token
    pub async fn retry_explanation(&self, signal: &TradingSignal, _retry_token: &str) -> ExplanationResult {
        // Just re-run the explanation (token is for audit trail)
        self.explain_signal(signal).await
    }

    /// Handle a follow-up question/chat message (no signal context)
    /// Used for continuing conversations after an explanation
    pub async fn chat_response(&self, conversation_context: &str, user_message: &str) -> Result<String> {
        // Build a simple prompt for chat mode
        let prompt = format!(
            r#"<|begin_of_text|><|start_header_id|>system<|end_header_id|>
You are a helpful quantitative analyst answering questions about trading signals and market analysis.
Keep responses concise and focused on the topic.
<|eot_id|><|start_header_id|>user<|end_header_id|>
Context from previous analysis:
{}

User question:
{}
<|eot_id|><|start_header_id|>assistant<|end_header_id|>
"#,
            conversation_context, user_message
        );

        // Call LLM with the prompt
        let response = self.llm.generate(&prompt, 500).await?;  // 500 token limit for chat responses
        Ok(response)
    }

    async fn explain_with_llm(&self, signal: &TradingSignal) -> Result<ExplanationResult> {
        // 1. Build query from signal context
        let query = self.build_query(signal);
        tracing::debug!("Built query for signal {}: {}", signal.id, query);

        // 2. Embed query
        let embed_start = std::time::Instant::now();
        let query_embedding = self.embedder.embed(&query).await?;
        let embed_duration = embed_start.elapsed();
        tracing::info!("Query embedding completed in {:.2}s for signal {}", embed_duration.as_secs_f64(), signal.id);

        // 3. Retrieve documents with active scope
        let retrieve_start = std::time::Instant::now();
        let docs = self
            .document_store
            .search(&query_embedding, 5, None)
            .await
            .unwrap_or_default();
        let retrieve_duration = retrieve_start.elapsed();
        let original_doc_count = docs.len();
        tracing::info!("Document retrieval completed in {:.2}s, found {} documents for signal {}", retrieve_duration.as_secs_f64(), original_doc_count, signal.id);

        // 4. Filter docs by active scope
        let filtered_docs: Vec<Document> = docs
            .into_iter()
            .filter(|doc| self.active_scope.matches_document(doc, None))
            .collect();
        tracing::debug!("Filtered {} documents to {} matching scope for signal {}", original_doc_count, filtered_docs.len(), signal.id);

        // 5. Build and execute prompt
        let prompt = self.build_cot_prompt(signal, &filtered_docs);
        let llm_start = std::time::Instant::now();
        tracing::debug!("Starting LLM generation for signal {}", signal.id);
        let raw_text = self.llm.generate(&prompt, 512).await?;
        let llm_duration = llm_start.elapsed();
        tracing::info!("LLM generation completed in {:.2}s for signal {}", llm_duration.as_secs_f64(), signal.id);

        // 6. Parse output
        let parse_start = std::time::Instant::now();
        let explanation = ExplanationParser::parse(&raw_text, signal.id.clone(), &filtered_docs);
        let parse_duration = parse_start.elapsed();
        tracing::debug!("Explanation parsing completed in {:.2}s for signal {}", parse_duration.as_secs_f64(), signal.id);

        // 7. Validate result
        match ExplanationParser::validate(&explanation) {
            Ok(()) => {
                tracing::info!("Explanation validation passed for signal {}", signal.id);
                return Ok(ExplanationResult::Success { explanation });
            }
            Err(e) => {
                tracing::warn!("Explanation validation failed: {} for signal {}", e, signal.id);
                // Return partial result
                return Ok(ExplanationResult::MissingDocuments {
                    explanation,
                    missing_docs: vec![],
                });
            }
        }
    }

    fn build_query(&self, signal: &TradingSignal) -> String {
        // Sanitize all text inputs to prevent embedding issues with special characters
        let direction = Self::sanitize_for_embedding(&signal.direction.to_lowercase());
        let policy_text = signal.context.recent_policy_events
            .iter()
            .map(|e| Self::sanitize_for_embedding(e))
            .collect::<Vec<_>>()
            .join(" ");
        
        format!(
            "natural gas {} trading grid stress {} degrees temperature anomaly {} policy {}",
            direction,
            signal.context.grid_stress_index,
            signal.context.temperature_anomaly,
            policy_text
        )
    }

    /// Sanitize text for embedding by removing/replacing problematic characters
    fn sanitize_for_embedding(text: &str) -> String {
        text
            .replace('\n', " ")  // Replace newlines with spaces
            .replace('\r', " ")  // Replace carriage returns with spaces
            .replace('\t', " ")  // Replace tabs with spaces
            .split_whitespace()  // Split on whitespace
            .collect::<Vec<_>>()
            .join(" ")           // Rejoin with single spaces
    }

    fn build_cot_prompt(&self, signal: &TradingSignal, docs: &[Document]) -> String {
        let evidence = if docs.is_empty() {
            "(No docs)".to_string()
        } else {
            docs.iter()
                .enumerate()
                .map(|(i, doc)| {
                    // Sanitize document content for safe embedding
                    let sanitized_content = Self::sanitize_for_embedding(&doc.content);
                    let excerpt = sanitized_content.chars().take(150).collect::<String>();
                    format!(
                        "[{}] {} ({}) - {}",
                        i + 1,
                        Self::sanitize_for_embedding(&doc.title),
                        Self::sanitize_for_embedding(&doc.source),
                        excerpt
                    )
                })
                .collect::<Vec<_>>()
                .join(" | ")  // Single line, pipe-separated
        };

        // Sanitize signal context for safe embedding
        let policy_event = signal.context.recent_policy_events
            .first()
            .map(|s| Self::sanitize_for_embedding(s))
            .unwrap_or_else(|| "none".to_string());

        format!(
            r#"<|begin_of_text|><|start_header_id|>system<|end_header_id|>
You are a quantitative analyst explaining trades with 8-step probabilistic reasoning.

Return ONLY VALID JSON. Structure as:
{{
  "summary": "1-2 sentence explanation",
  "reference_class": {{"class_name": "...", "base_rate": 0.75, "sample_size": 50, "reasoning": "..."}},
  "ensemble": {{"components": [{{"source": "...", "signal": 0.5, "confidence": 0.8, "weight": 0.33}}], "final_signal": 0.45, "agreement": 0.85}},
  "bayesian_update": {{"prior": 0.5, "likelihood_ratio": 2.5, "posterior": 0.67, "evidence_summary": "..."}},
  "scenarios": [{{"name": "Cold Snap", "probability": 0.4, "payoff": 0.15, "payoff_min": 0.10, "payoff_max": 0.20, "description": "..."}}],
  "expected_value": {{"expected_return": 0.08, "volatility": 0.12, "sharpe_ratio": 0.67, "kelly_position_size": 0.03, "interpretation": "..."}},
  "risk_assessment": {{"worst_case": -0.25, "worst_case_probability": 0.05, "tail_risk_probability": 0.01, "recovery_days": 30, "concentration_risks": ["..."], "liquidity_assessment": "...", "risk_checklist": [{{"name": "Check1", "passed": true}}]}},
  "confidence": 0.75
}}
<|eot_id|><|start_header_id|>user<|end_header_id|>
## Trade: {} {} @{:.0}% confidence, ${:.2}, grid {}/100, policy: {}
Evidence: {}

Analyze using ALL 8 steps. Return JSON only.
<|eot_id|><|start_header_id|>assistant<|end_header_id|>
"#,
            signal.instrument,
            signal.direction.to_uppercase(),
            signal.confidence * 100.0,
            signal.context.current_price,
            signal.context.grid_stress_index,
            policy_event,
            evidence
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;

    #[tokio::test]
    async fn test_explanation_pipeline_mock() {
        let signal = TradingSignal {
            id: "test_signal".to_string(),
            instrument: "NG".to_string(),
            direction: "BUY".to_string(),
            confidence: 0.75,
            timestamp: Utc::now(),
            context: crate::types::TradingContext {
                current_price: 3.45,
                grid_stress_index: 75.0,
                temperature_anomaly: 5.5,
                recent_policy_events: vec!["FERC order".to_string()],
                primary_region: "ERCOT".to_string(),
            },
        };

        let rag = ExplainabilityRAG::new(
            "dummy_model.gguf",
            "dummy_db.db",
            true, // mock mode
        )
        .await
        .expect("Failed to create RAG");

        let result = rag.explain_signal(&signal).await;

        // In mock mode, should get some kind of response
        match result {
            ExplanationResult::Success { .. } | ExplanationResult::TemplateFallback { .. } => {
                // Expected
            }
            _ => panic!("Unexpected result type"),
        }
    }
}
