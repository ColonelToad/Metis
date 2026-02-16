use crate::types::{Citation, Document, Explanation};
use chrono::Utc;
use regex::Regex;
use std::collections::HashMap;

/// Heuristic parser for LLM-generated explanations
/// Supports both JSON and free-form text with graceful fallback
pub struct ExplanationParser;

impl ExplanationParser {
    /// Parse raw LLM output into structured Explanation
    /// Tries JSON first, then falls back to heuristic text parsing
    pub fn parse(
        raw_text: &str,
        signal_id: String,
        available_docs: &[Document],
    ) -> Explanation {
        // First, try to parse as JSON
        if let Ok(parsed) = Self::parse_json(raw_text, signal_id.clone(), available_docs) {
            return parsed;
        }

        // Fallback: parse as free-form text with regex
        Self::parse_text(raw_text, signal_id, available_docs)
    }

    /// Try to parse JSON output from LLM
    fn parse_json(
        raw_text: &str,
        signal_id: String,
        available_docs: &[Document],
    ) -> Result<Explanation, Box<dyn std::error::Error>> {
        // Extract JSON from response (may have text before/after)
        let json_start = raw_text.find('{').ok_or("No JSON object found")?;
        let json_end = raw_text.rfind('}').ok_or("No JSON end found")?;
        let json_str = &raw_text[json_start..=json_end];

        let parsed: serde_json::Value = serde_json::from_str(json_str)?;

        let market_analysis = parsed["probabilistic_forecast"]
            .as_str()
            .or_else(|| parsed["market_analysis"].as_str())
            .map(|s| s.to_string());

        let signal_drivers = parsed["signal_drivers"]
            .as_str()
            .map(|s| s.to_string());

        let risks = parsed["risks"]
            .as_str()
            .map(|s| s.to_string());

        let expected_outcome = parsed["expected_value"]
            .as_str()
            .or_else(|| parsed["expected_outcome"].as_str())
            .map(|s| s.to_string());

        let confidence_json = parsed["confidence"].as_f64().unwrap_or(0.7);

        // Extract citations if present in JSON
        let citations = if let Some(citations_arr) = parsed["citations"].as_array() {
            citations_arr
                .iter()
                .filter_map(|c| {
                    Some(Citation {
                        doc_id: c["doc_id"].as_str()?.to_string(),
                        title: c["title"].as_str()?.to_string(),
                        source: c["source"].as_str()?.to_string(),
                        excerpt: c["excerpt"].as_str()?.to_string(),
                    })
                })
                .collect()
        } else {
            // Fallback: extract citation references from text fields
            Self::extract_citations_from_text(
                &format!(
                    "{} {} {} {}",
                    market_analysis.as_deref().unwrap_or(""),
                    signal_drivers.as_deref().unwrap_or(""),
                    risks.as_deref().unwrap_or(""),
                    expected_outcome.as_deref().unwrap_or("")
                ),
                available_docs,
            )
        };

        Ok(Explanation {
            signal_id,
            market_analysis,
            signal_drivers,
            risks,
            expected_outcome,
            citations,
            raw_text: raw_text.to_string(),
            confidence_score: confidence_json,
            generated_at: Utc::now(),
        })
    }

    /// Fallback parser for free-form text output
    fn parse_text(
        raw_text: &str,
        signal_id: String,
        available_docs: &[Document],
    ) -> Explanation {
        let market_analysis = Self::extract_section(raw_text, &["Probabilistic Forecast", "Market Condition"]);
        let signal_drivers = Self::extract_section(raw_text, &["Signal Drivers", "Reference Class", "Ensemble"]);
        let risks = Self::extract_section(raw_text, &["Risk", "Risk Assessment", "Risk Factors"]);
        let expected_outcome = Self::extract_section(raw_text, &["Expected Value", "Expected Outcome", "Forecast"]);

        let citations = Self::extract_citations_from_text(raw_text, available_docs);
        let confidence_score = Self::estimate_confidence(&raw_text);

        Explanation {
            signal_id,
            market_analysis,
            signal_drivers,
            risks,
            expected_outcome,
            citations,
            raw_text: raw_text.to_string(),
            confidence_score,
            generated_at: Utc::now(),
        }
    }

    /// Extract a section from raw text using header patterns
    /// Returns None if section not found (graceful degradation)
    fn extract_section(text: &str, headers: &[&str]) -> Option<String> {
        // Try each header variant
        for header in headers {
            // Pattern: find header (case-insensitive), capture until next ## or end
            let pattern = format!(
                r"(?i)^[#\s]*{}[:\s]*\n(.*?)(?=\n##|$)",
                regex::escape(header)
            );

            if let Ok(re) = Regex::new(&pattern) {
                if let Some(caps) = re.captures(text) {
                    let section = caps.get(1).map(|m| m.as_str().trim().to_string());
                    if section.is_some() {
                        return section;
                    }
                }
            }
        }

        None
    }

    /// Extract citations from raw text [Doc N] references
    /// Maps back to Document objects from available_docs
    fn extract_citations_from_text(raw_text: &str, available_docs: &[Document]) -> Vec<Citation> {
        let mut citations = Vec::new();

        // Pattern: [Doc N] or [N] where N is 1-indexed
        if let Ok(re) = Regex::new(r"\[Doc? ?(\d+)\]") {
            let doc_indices: HashMap<usize, bool> = re
                .captures_iter(raw_text)
                .filter_map(|cap| {
                    cap.get(1)
                        .and_then(|m| m.as_str().parse::<usize>().ok())
                        .map(|idx| (idx, true))
                })
                .collect();

            // Convert to 0-indexed and fetch documents
            for (idx, _) in doc_indices {
                if idx > 0 && idx <= available_docs.len() {
                    let doc = &available_docs[idx - 1];
                    let excerpt = &doc.content[..doc.content.len().min(200)];

                    citations.push(Citation {
                        doc_id: doc.id.clone(),
                        title: doc.title.clone(),
                        source: doc.source.clone(),
                        excerpt: excerpt.to_string(),
                    });
                }
            }
        }

        citations
    }

    /// Estimate confidence score based on text quality signals
    /// 0.0 (low) to 1.0 (high)
    fn estimate_confidence(raw_text: &str) -> f64 {
        let mut score: f64 = 0.5;  // Base score

        // Boost for key signals
        let text_len = raw_text.len();
        if text_len > 200 {
            score += 0.15;  // Detailed response
        }
        if text_len > 500 {
            score += 0.1;   // Very detailed
        }

        // Boost for probabilistic language
        if raw_text.contains('%') || raw_text.contains("probability") {
            score += 0.15;
        }

        // Boost for scenario thinking
        if raw_text.contains("scenario") || raw_text.contains("outcome") {
            score += 0.1;
        }

        // Boost for citations
        if raw_text.contains("[Doc") {
            score += 0.1;
        }

        // Reduce for vague language
        if raw_text.contains("maybe") || raw_text.contains("possibly") {
            score -= 0.05;
        }

        let min_score = score.min(1.0);
        min_score.max(0.0)  // Clamp [0, 1]
    }

    /// Validate explanation has minimum quality
    pub fn validate(explanation: &Explanation) -> Result<(), String> {
        // Check: has content
        if explanation.raw_text.trim().is_empty() {
            return Err("Empty explanation".to_string());
        }

        // Check: reasonable length (not truncated)
        if explanation.raw_text.len() < 100 {
            return Err("Explanation too short (may be truncated)".to_string());
        }

        // Check: has at least some structured content
        let has_analysis = explanation.market_analysis.is_some();
        let has_drivers = explanation.signal_drivers.is_some();
        let _has_citations = !explanation.citations.is_empty();

        if !has_analysis && !has_drivers {
            return Err("No structured analysis found".to_string());
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;

    fn create_test_doc(id: &str, title: &str) -> Document {
        Document {
            id: id.to_string(),
            title: title.to_string(),
            content: "Test content for the document".to_string(),
            source: "TEST".to_string(),
            category: "test".to_string(),
            timestamp: Utc::now(),
        }
    }

    #[test]
    fn test_extract_section_with_header() {
        let text = "## Market Analysis\n\nThis is the market analysis content.\n\n## Signal Drivers\n\nOther content";
        let section = ExplanationParser::extract_section(text, &["Market Analysis"]);
        assert!(section.is_some());
        assert!(section.unwrap().contains("market analysis content"));
    }

    #[test]
    fn test_extract_section_case_insensitive() {
        let text = "## MARKET analysis\n\nContent here.\n\n## Other";
        let section = ExplanationParser::extract_section(text, &["market analysis"]);
        assert!(section.is_some());
    }

    #[test]
    fn test_extract_section_missing_returns_none() {
        let text = "## Some Other Section\n\nContent";
        let section = ExplanationParser::extract_section(text, &["Market Analysis"]);
        assert!(section.is_none());
    }

    #[test]
    fn test_extract_citations() {
        let text = "As shown in [Doc 1], the market trends indicate [Doc 2] supports the signal.";
        let docs = vec![
            create_test_doc("doc1", "Market Trends"),
            create_test_doc("doc2", "Supporting Data"),
        ];

        let citations = ExplanationParser::extract_citations(text, &docs);
        assert_eq!(citations.len(), 2);
        assert_eq!(citations[0].title, "Market Trends");
        assert_eq!(citations[1].title, "Supporting Data");
    }

    #[test]
    fn test_extract_citations_invalid_index() {
        let text = "Reference [Doc 999] doesn't exist.";
        let docs = vec![create_test_doc("doc1", "Only Doc")];

        let citations = ExplanationParser::extract_citations(text, &docs);
        assert_eq!(citations.len(), 0);
    }

    #[test]
    fn test_confidence_scoring() {
        let short = "Brief.";
        let long = "This is a very detailed explanation with lots of content and multiple paragraphs explaining the reasoning process.";
        let with_probability = "There is a 70% probability that the market will move upward given these conditions.";

        let score_short = ExplanationParser::estimate_confidence(short);
        let score_long = ExplanationParser::estimate_confidence(long);
        let score_prob = ExplanationParser::estimate_confidence(with_probability);

        assert!(score_long > score_short);
        assert!(score_prob > score_short);
    }

    #[test]
    fn test_parse_full_explanation() {
        let raw = r#"## Probabilistic Forecast
There is a 70% chance prices will increase [Doc 1].

## Signal Drivers
Grid stress combined with weather anomalies [Doc 2] drove this signal.

## Risk Assessment
Main risk is demand normalization.

This signal has high confidence based on ensemble agreement."#;

        let docs = vec![
            create_test_doc("doc1", "Price Forecast"),
            create_test_doc("doc2", "Weather Data"),
        ];

        let explanation = ExplanationParser::parse(raw, "signal123".to_string(), &docs);

        assert_eq!(explanation.signal_id, "signal123");
        assert!(explanation.market_analysis.is_some());
        assert!(explanation.signal_drivers.is_some());
        assert!(explanation.risks.is_some());
        assert_eq!(explanation.citations.len(), 2);
        assert!(explanation.confidence_score > 0.5);
    }

    #[test]
    fn test_validate_empty_explanation() {
        let bad_explanation = Explanation {
            signal_id: "test".to_string(),
            market_analysis: None,
            signal_drivers: None,
            risks: None,
            expected_outcome: None,
            citations: vec![],
            raw_text: "".to_string(),
            confidence_score: 0.5,
            generated_at: Utc::now(),
        };

        assert!(ExplanationParser::validate(&bad_explanation).is_err());
    }

    #[test]
    fn test_validate_good_explanation() {
        let good_explanation = Explanation {
            signal_id: "test".to_string(),
            market_analysis: Some("Market analysis content".to_string()),
            signal_drivers: None,
            risks: None,
            expected_outcome: None,
            citations: vec![],
            raw_text: "This is a detailed explanation with substantial content".to_string(),
            confidence_score: 0.7,
            generated_at: Utc::now(),
        };

        assert!(ExplanationParser::validate(&good_explanation).is_ok());
    }
}
