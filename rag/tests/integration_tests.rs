// Integration tests for the complete RAG explanation pipeline
#[cfg(test)]
mod tests {
    use rag::*;

    fn create_test_signal() -> TradingSignal {
        TradingSignal {
            id: "test_ng_001".to_string(),
            instrument: "NG_MAR26".to_string(),
            direction: "LONG".to_string(),
            confidence: 0.82,
            context: serde_json::json!({
                "current_price": 3.45,
                "grid_stress_index": 73,
                "temperature_anomaly": -22,
                "recent_policy_events": ["H.R. 1234 advancing"],
                "primary_region": "ERCOT"
            }),
        }
    }

    fn create_test_documents() -> Vec<Document> {
        vec![
            Document {
                doc_id: "eia_storage_001".to_string(),
                title: "EIA Natural Gas Storage Report (Jan 9, 2026)".to_string(),
                source: "EIA".to_string(),
                category: "storage".to_string(),
                content: "Natural gas in storage declined by 180 Bcf, bringing total storage to 2,450 Bcf, 18% below the 5-year average.".to_string(),
                embedding: vec![0.1; 384],
                metadata: Some(serde_json::json!({
                    "date": "2026-01-09",
                    "tags": ["storage", "supply"],
                    "focus_weight": 2.0
                })),
                created_at: "2026-01-09".to_string(),
            },
            Document {
                doc_id: "noaa_forecast_001".to_string(),
                title: "NOAA GFS Ensemble Forecast (Jan 14, 2026)".to_string(),
                source: "NOAA".to_string(),
                category: "weather".to_string(),
                content: "Polar vortex expected to dip into central US with 70% probability. Temperatures 20-30°F below seasonal averages.".to_string(),
                embedding: vec![0.2; 384],
                metadata: Some(serde_json::json!({
                    "date": "2026-01-14",
                    "tags": ["weather", "temperature"],
                    "focus_weight": 1.5
                })),
                created_at: "2026-01-14".to_string(),
            },
            Document {
                doc_id: "congress_hr1234_001".to_string(),
                title: "Congressional Bill Tracker (H.R. 1234)".to_string(),
                source: "Congress.gov".to_string(),
                category: "policy".to_string(),
                content: "Clean Energy Tax Credits bill advancing through committee. Expected to increase renewable penetration.".to_string(),
                embedding: vec![0.3; 384],
                metadata: Some(serde_json::json!({
                    "date": "2026-01-14",
                    "tags": ["policy", "renewables"],
                    "focus_weight": 1.0
                })),
                created_at: "2026-01-14".to_string(),
            },
        ]
    }

    #[test]
    fn test_document_scope_recent_weather() {
        let scope = DocumentScope::recent_weather_grid(7);

        // Weather document should match
        let weather_doc = Document {
            doc_id: "noaa_001".to_string(),
            title: "Weather Forecast".to_string(),
            source: "NOAA".to_string(),
            category: "weather".to_string(),
            content: "Cold front incoming".to_string(),
            embedding: vec![0.0; 384],
            metadata: None,
            created_at: chrono::Local::now().format("%Y-%m-%d").to_string(),
        };

        assert!(scope.matches_document(&weather_doc));
    }

    #[test]
    fn test_document_scope_filtering() {
        let scope = DocumentScope::builder()
            .add_source_filter("EIA")
            .add_category_filter("storage")
            .build();

        let matching_doc = Document {
            doc_id: "eia_001".to_string(),
            title: "Storage Report".to_string(),
            source: "EIA".to_string(),
            category: "storage".to_string(),
            content: "Storage levels".to_string(),
            embedding: vec![0.0; 384],
            metadata: None,
            created_at: chrono::Local::now().format("%Y-%m-%d").to_string(),
        };

        let non_matching_doc = Document {
            doc_id: "noaa_001".to_string(),
            title: "Weather".to_string(),
            source: "NOAA".to_string(),
            category: "weather".to_string(),
            content: "Forecast".to_string(),
            embedding: vec![0.0; 384],
            metadata: None,
            created_at: chrono::Local::now().format("%Y-%m-%d").to_string(),
        };

        assert!(scope.matches_document(&matching_doc));
        assert!(!scope.matches_document(&non_matching_doc));
    }

    #[test]
    fn test_explanation_parser_success() {
        let llm_output = r#"
## Market Analysis
Natural gas futures are trading at $3.45/MMBtu. The market shows backwardation, signaling supply concerns.

## Signal Drivers
Cold snap expected this week (70% probability). Storage levels 18% below 5-year average.

## Expected Outcome
NG expected to rise to $3.70-3.80 (+7-10%) within 5 days.

## Risk Assessment
Weather forecast uncertainty, storage report could show surprise build.
"#;

        let docs = create_test_documents();
        let result = ExplanationParser::parse(llm_output, "test_001", &docs);

        assert!(result.market_analysis.is_some());
        assert!(result.signal_drivers.is_some());
        assert!(result.expected_outcome.is_some());
        assert!(result.risks.is_some());
    }

    #[test]
    fn test_explanation_parser_missing_sections() {
        let llm_output = r#"
Natural gas prices are rising due to cold weather and storage deficits.
This is a simple response without structured sections.
"#;

        let docs = create_test_documents();
        let result = ExplanationParser::parse(llm_output, "test_001", &docs);

        // Parser should gracefully handle missing sections
        // At least raw_text should be populated
        assert!(!result.raw_text.is_empty());
    }

    #[test]
    fn test_explanation_parser_citation_extraction() {
        let llm_output = r#"
## Market Analysis
Natural gas is affected by storage levels [Doc 1]. Weather patterns will drive prices [Doc 2].

## Expected Outcome
Based on policy trends [Doc 3], we expect prices to rise.
"#;

        let docs = create_test_documents();
        let result = ExplanationParser::parse(llm_output, "test_001", &docs);

        // Should extract citations
        assert!(!result.citations.is_empty());
    }

    #[test]
    fn test_explanation_parser_confidence_scoring() {
        // High-confidence response
        let high_confidence = r#"
## Market Analysis
Detailed analysis with multiple factors: cold snap, storage deficits, grid stress.

## Signal Drivers
1. Weather: 70% probability of polar vortex
2. Supply: 18% storage deficit vs 5-year average
3. Demand: ERCOT stress at 73/100

## Expected Outcome
Clear probabilistic outcome: Base 60%, Upside 25%, Downside 15%.

## Risk Assessment
Specific risks: forecast uncertainty (30%), storage report timing.
"#;

        let low_confidence = "Maybe prices go up or down.";

        let docs = create_test_documents();
        let high_result = ExplanationParser::parse(high_confidence, "test_001", &docs);
        let low_result = ExplanationParser::parse(low_confidence, "test_001", &docs);

        assert!(high_result.confidence_score > low_result.confidence_score);
    }

    #[test]
    fn test_result_type_json_serialization() {
        let explanation = Explanation {
            signal_id: "test_001".to_string(),
            market_analysis: Some("Market is bullish".to_string()),
            signal_drivers: Some("Cold weather incoming".to_string()),
            risks: Some("Forecast uncertainty".to_string()),
            expected_outcome: Some("Price rises 5-10%".to_string()),
            citations: vec![],
            raw_text: "Full LLM output here".to_string(),
            confidence_score: 0.85,
            generated_at: chrono::Utc::now().to_rfc3339(),
        };

        // Test that all result types serialize properly
        let success_result = ExplanationResult::Success {
            explanation: explanation.clone(),
        };

        let json = serde_json::to_string(&success_result).expect("Should serialize");
        assert!(json.contains("\"Success\"") || json.contains("success"));

        // Test timeout result
        let timeout_result = ExplanationResult::Timeout {
            partial_explanation: explanation.clone(),
            retry_token: "token_abc123".to_string(),
        };

        let json = serde_json::to_string(&timeout_result).expect("Should serialize");
        assert!(json.contains("retry_token") || json.contains("Timeout"));

        // Test fallback result
        let fallback_result = ExplanationResult::TemplateFallback {
            explanation,
            reason: "LLM inference failed".to_string(),
        };

        let json = serde_json::to_string(&fallback_result).expect("Should serialize");
        assert!(json.contains("TemplateFallback") || json.contains("fallback"));
    }

    #[test]
    fn test_signal_has_required_fields() {
        let signal = create_test_signal();

        assert!(!signal.id.is_empty());
        assert!(!signal.instrument.is_empty());
        assert!(signal.confidence >= 0.0 && signal.confidence <= 1.0);
        assert!(signal.context.get("current_price").is_some());
    }

    #[test]
    fn test_document_has_valid_embedding() {
        let doc = Document {
            doc_id: "test_001".to_string(),
            title: "Test Document".to_string(),
            source: "TEST".to_string(),
            category: "test".to_string(),
            content: "Test content".to_string(),
            embedding: vec![0.5; 384], // 384 dimensions for all-MiniLM-L6-v2
            metadata: None,
            created_at: "2026-01-14".to_string(),
        };

        // Embedding should be correct dimension
        assert_eq!(doc.embedding.len(), 384);

        // Values should be normalized floats
        for val in &doc.embedding {
            assert!(*val >= -1.0 && *val <= 1.0);
        }
    }

    #[test]
    fn test_scope_relevance_multiplier() {
        let scope = DocumentScope::recent_congress_bills(7);

        let congress_doc = Document {
            doc_id: "hr1234".to_string(),
            title: "Bill".to_string(),
            source: "Congress.gov".to_string(),
            category: "policy".to_string(),
            content: "Bill text".to_string(),
            embedding: vec![0.0; 384],
            metadata: None,
            created_at: chrono::Local::now().format("%Y-%m-%d").to_string(),
        };

        let multiplier = scope.relevance_multiplier(&congress_doc);
        // Congress scope should boost congress documents
        assert!(multiplier >= 1.0);
    }

    #[test]
    fn test_cross_source_scope_includes_multiple_sources() {
        let scope =
            DocumentScope::cross_source(vec!["EIA", "NOAA", "Congress.gov"], "multi_source");

        let eia_doc = Document {
            doc_id: "eia_001".to_string(),
            title: "Storage".to_string(),
            source: "EIA".to_string(),
            category: "storage".to_string(),
            content: "Content".to_string(),
            embedding: vec![0.0; 384],
            metadata: None,
            created_at: "2026-01-14".to_string(),
        };

        let noaa_doc = Document {
            doc_id: "noaa_001".to_string(),
            title: "Weather".to_string(),
            source: "NOAA".to_string(),
            category: "weather".to_string(),
            content: "Content".to_string(),
            embedding: vec![0.0; 384],
            metadata: None,
            created_at: "2026-01-14".to_string(),
        };

        assert!(scope.matches_document(&eia_doc));
        assert!(scope.matches_document(&noaa_doc));
    }
}
