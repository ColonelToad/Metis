use crate::{
    document_scope::DocumentScope,
    document_store::DocumentStore,
    embedding::EmbeddingEngine,
    explanation_parser::ExplanationParser,
    llm::LocalLLMEngine,
    types::{Document, Explanation, TradingSignal},
};
use anyhow::Result;
use std::sync::Arc;
use tokio::sync::Mutex;

/// Multi-hop reasoning chain for evidence-grounded explanation generation
/// Implements: decompose → retrieve → summarize → retrieve (conditioned) → synthesize → validate
pub struct ReasoningChain {
    llm: Arc<LocalLLMEngine>,
    embedder: Arc<EmbeddingEngine>,
    document_store: Arc<Mutex<DocumentStore>>,
}

impl ReasoningChain {
    pub fn new(
        llm: Arc<LocalLLMEngine>,
        embedder: Arc<EmbeddingEngine>,
        document_store: Arc<Mutex<DocumentStore>>,
    ) -> Self {
        Self {
            llm,
            embedder,
            document_store,
        }
    }

    /// Execute the full multi-hop reasoning chain
    pub async fn reason(&self, signal: &TradingSignal) -> Result<Explanation> {
        // Step 1: Decompose query into layer-specific questions
        let (layer1_query, layer2_query) = self.decompose_query(signal).await?;
        tracing::debug!(
            "Decomposed signal {} into L1: '{}' L2: '{}'",
            signal.id,
            layer1_query,
            layer2_query
        );

        // Step 2: Retrieve physical layer documents (Layer 1: "what")
        let scope_l1 = DocumentScope::recent_eia_reports(30);
        let layer1_docs = self.retrieve_documents(&layer1_query, &scope_l1, 3).await?;
        tracing::info!(
            "Layer 1 retrieval returned {} documents for signal {}",
            layer1_docs.len(),
            signal.id
        );

        // Step 3: Summarize Layer 1 findings
        let layer1_summary = if !layer1_docs.is_empty() {
            self.summarize_documents(&layer1_docs).await?
        } else {
            "(No physical layer documents available)".to_string()
        };
        tracing::debug!("Layer 1 summary: {}", layer1_summary);

        // Step 4: Retrieve structural constraint documents, conditioned on Layer 1 summary
        // This is the "hierarchical" multi-hop step: Layer 2 is informed by Layer 1
        let conditioned_l2_query = format!("{} Given context: {}", layer2_query, layer1_summary);
        let scope_l2 =
            DocumentScope::cross_source(&["FERC", "Congress", "OFAC"], "structural_constraints");
        let layer2_docs = self
            .retrieve_documents(&conditioned_l2_query, &scope_l2, 3)
            .await?;
        tracing::info!(
            "Layer 2 (conditioned) retrieval returned {} documents for signal {}",
            layer2_docs.len(),
            signal.id
        );

        // Step 5: Synthesize full explanation using both layers
        let explanation = self
            .synthesize_explanation(signal, &layer1_summary, &layer2_docs)
            .await?;

        // Step 6: Validate and retry once on failure
        match ExplanationParser::validate(&explanation) {
            Ok(()) => {
                tracing::info!("Explanation validation passed for signal {}", signal.id);
                Ok(explanation)
            }
            Err(e) => {
                tracing::warn!(
                    "Initial synthesis validation failed: {}. Retrying for signal {}",
                    e,
                    signal.id
                );
                // Retry synthesis once
                match self
                    .synthesize_explanation(signal, &layer1_summary, &layer2_docs)
                    .await
                {
                    Ok(retry_explanation) => {
                        match ExplanationParser::validate(&retry_explanation) {
                            Ok(()) => {
                                tracing::info!("Retry validation passed for signal {}", signal.id);
                                Ok(retry_explanation)
                            }
                            Err(_) => {
                                // Return the retry attempt even if validation fails
                                tracing::warn!(
                                    "Retry validation also failed for signal {}",
                                    signal.id
                                );
                                Ok(retry_explanation)
                            }
                        }
                    }
                    Err(retry_err) => {
                        tracing::error!(
                            "Retry synthesis failed: {} for signal {}",
                            retry_err,
                            signal.id
                        );
                        // Return original explanation on retry error
                        Ok(explanation)
                    }
                }
            }
        }
    }

    /// Decompose the trading signal into Layer 1 and Layer 2 specific queries
    async fn decompose_query(&self, signal: &TradingSignal) -> Result<(String, String)> {
        // Layer 1: physical market conditions
        let layer1 = format!(
            "What is the current natural gas {} outlook? Market conditions, storage, supply {}",
            if signal.direction == "LONG" {
                "bullish"
            } else {
                "bearish"
            },
            signal.context.grid_stress_index
        );

        // Layer 2: structural/policy constraints
        let layer2 = format!(
            "What regulatory, pipeline capacity, or policy factors {} supply for natural gas in {}?",
            if signal.direction == "LONG" { "support" } else { "limit" },
            signal.context.primary_region
        );

        Ok((layer1, layer2))
    }

    /// Retrieve documents matching a query and scope
    async fn retrieve_documents(
        &self,
        query: &str,
        scope: &DocumentScope,
        top_k: usize,
    ) -> Result<Vec<Document>> {
        // Embed the query
        let query_embedding = self.embedder.embed(query).await?;

        // Search via document store
        let store = self.document_store.lock().await;
        let mut docs = store.search(&query_embedding, top_k, None).await?;

        // Filter by scope and apply relevance multiplier
        //docs.retain(|doc| scope.matches_document(doc, None));

        Ok(docs)
    }

    /// Summarize retrieved documents into a brief contextual summary
    async fn summarize_documents(&self, docs: &[Document]) -> Result<String> {
        if docs.is_empty() {
            return Ok("No documents to summarize".to_string());
        }

        // Build a prompt that asks the LLM to summarize the documents
        let evidence = docs
            .iter()
            .enumerate()
            .map(|(i, doc)| {
                format!(
                    "[{}] {} ({}) - {}",
                    i + 1,
                    doc.title,
                    doc.source,
                    &doc.content[..std::cmp::min(15000, doc.content.len())]
                )
            })
            .collect::<Vec<_>>()
            .join("\n\n");

        let prompt = format!(
            r#"<|im_start|>system
Summarize these market documents concisely in 2-3 sentences, focusing on implications for natural gas pricing.
<|im_end|>
<|im_start|>user
Documents:
{}
<|im_end|>
<|im_start|>assistant
"#,
            evidence
        );

        // INCREASE tokens from 150 to 500 so it can finish thinking
        let raw_summary = self.llm.generate(&prompt, 500).await?;

        let summary = crate::think_strip::strip_think_block(&raw_summary).unwrap_or_else(|| {
            "(Summary generation was truncated due to context limits)".to_string()
        });

        tracing::debug!("Document summary: {}", summary);
        Ok(summary)
    }

    /// Synthesize the full explanation using both layers of context
    async fn synthesize_explanation(
        &self,
        signal: &TradingSignal,
        layer1_summary: &str,
        layer2_docs: &[Document],
    ) -> Result<Explanation> {
        // Build evidence section with Layer 2 documents
        let evidence = if layer2_docs.is_empty() {
            "(No structural constraint documents)".to_string()
        } else {
            layer2_docs
                .iter()
                .enumerate()
                .map(|(i, doc)| {
                    let excerpt = &doc.content[..std::cmp::min(20000, doc.content.len())];
                    format!("[{}] {} ({}) - {}", i + 1, doc.title, doc.source, excerpt)
                })
                .collect::<Vec<_>>()
                .join(" | ")
        };

        // Compute the deterministic reasoning pass BEFORE prompting the LLM.
        // These numbers become the authoritative source for
        // scenarios/expected_value/risk_assessment (set below, after
        // parsing) — the LLM is only asked for narrative fields, and is
        // handed the computed numbers as grounding context so it explains
        // real numbers instead of inventing its own. See
        // deterministic_reasoning.rs for what this maps and why.
        let deterministic = crate::deterministic_reasoning::compute(signal);

        let prompt = format!(
            r#"<|im_start|>system
You are a quantitative trading analyst. Your output must be a single, valid JSON object. 
Analyze the provided context and populate the fields below with your actual reasoning. DO NOT output placeholder text.
The scenario/expected-value/risk numbers in the context are already computed — do not restate or recompute them, just explain what's driving them.

TEMPLATE:
{{
  "market_analysis": "Write a 2-3 sentence summary of the physical market conditions based on the context.",
  "signal_drivers": "Explain the structural or policy factors driving this signal.",
  "risks": "Identify the primary risks based on the documents and the computed risk numbers.",
  "expected_outcome": "What is the expected outcome of this trade, given the computed expected value below?",
  "confidence_score": 0.85
}}
<|im_end|>
<|im_start|>user
## Trade: {} {} @{:.0}% confidence, ${:.2}

### Market Context (from physical layer analysis):
{}

### Structural Constraints & Policy (Layer 2):
{}

### Computed Reasoning (deterministic, already calculated — explain, don't recompute):
{}

Synthesize the context into the JSON template provided. Return JSON only.
<|im_end|>
<|im_start|>assistant
"#,
            signal.instrument,
            signal.direction.to_uppercase(),
            signal.confidence * 100.0,
            signal.context.current_price,
            layer1_summary,
            evidence,
            deterministic.grounding_context
        );

        println!("\n================ PROMPT DEBUG ================");
        println!("{}", prompt);
        println!("==============================================\n");

        let raw_response = self.llm.generate(&prompt, 800).await?;

        // 1. BULLETPROOF JSON EXTRACTION
        let mut json_str = raw_response.as_str();

        // Slice away the <think> block entirely if it exists
        if let Some(idx) = json_str.rfind("</think>") {
            json_str = &json_str[idx + "</think>".len()..];
        }

        // Find the absolute first '{' and absolute last '}' in whatever is left
        let cleaned_json =
            if let (Some(start), Some(end)) = (json_str.find('{'), json_str.rfind('}')) {
                &json_str[start..=end]
            } else {
                json_str
            };

        // 2. FORCE PRINT TO CONSOLE (Bypass tracing log levels)
        println!("\n========================================================");
        println!("RAW LLM RESPONSE EXTRACTED FOR PARSING:");
        println!("{}", cleaned_json);
        println!("========================================================\n");

        // Parse the cleaned JSON response for the narrative fields
        let mut explanation = ExplanationParser::parse(cleaned_json, signal.id.clone(), layer2_docs);

        // Overwrite the structured fields with the deterministic computation
        // regardless of what (if anything) the LLM said about them — the
        // prompt no longer asks for these, but if an older-style response
        // ever included them anyway, the computed numbers still win.
        explanation.scenarios = Some(deterministic.scenarios);
        explanation.expected_value = Some(deterministic.expected_value);
        explanation.risk_assessment = Some(deterministic.risk_assessment);

        Ok(explanation)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;

    #[tokio::test]
    async fn test_decompose_query() {
        let chain = ReasoningChain::new(
            Arc::new(LocalLLMEngine::new("dummy.gguf", true).unwrap()),
            Arc::new(EmbeddingEngine::new(true).unwrap()),
            Arc::new(Mutex::new(
                DocumentStore::new("mock.db", true).await.unwrap(),
            )),
        );

        let signal = TradingSignal {
            id: "test".to_string(),
            instrument: "NG".to_string(),
            direction: "LONG".to_string(),
            confidence: 0.75,
            timestamp: Utc::now(),
            context: crate::types::TradingContext {
                current_price: 3.0,
                grid_stress_index: 75.0,
                temperature_anomaly: 5.0,
                recent_policy_events: vec!["FERC Order".to_string()],
                primary_region: "ERCOT".to_string(),
            },
        };

        let (l1, l2) = chain.decompose_query(&signal).await.unwrap();
        assert!(!l1.is_empty());
        assert!(!l2.is_empty());
        assert!(l1.contains("bullish")); // LONG signal
        assert!(l2.contains("support")); // LONG signal
    }
}
