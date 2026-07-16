use crate::types::{Explanation, TradingSignal};
use chrono::Utc;

pub struct TemplateEngine;

impl TemplateEngine {
    pub fn new() -> Self {
        Self
    }

    pub fn generate(&self, signal: &TradingSignal) -> Explanation {
        // This fallback used to leave scenarios/expected_value/risk_assessment
        // as None and the narrative as a fixed Mad-Libs paragraph — no real
        // computation happened here even though the deterministic reasoning
        // engine (engine::reasoning) existed and could compute real numbers
        // with no LLM required. It's used now, so the "no LLM available"
        // path is a real degraded mode, not a fake one.
        let deterministic = crate::deterministic_reasoning::compute(signal);

        let text = format!(
            r#"Trading Signal Analysis (Template-Based)

## Signal Overview
- Instrument: {}
- Action: {}
- Confidence: {:.1}%
- Timestamp: {}

## Market Context
- Current Price: ${:.2}
- Grid Stress: {:.1}/100 ({})
- Weather Anomaly: {:.1}°F above normal
- Recent Policy Events: {}

## Analysis
This {} signal was generated based on quantitative models analyzing grid stress, weather patterns, and policy events. The confidence level of {:.1}% reflects the model's assessment of signal quality.

## Risk Factors
- Normal market volatility
- Potential data lag in external feeds
- Model assumptions may not capture all market dynamics

## Computed Reasoning (deterministic, no LLM required)
{}

Note: This is a template-based explanation — narrative text is fixed, but the
scenarios/expected-value/risk numbers above are real, computed by
engine::reasoning, not placeholders. Full chain-of-thought analysis
(LLM-generated narrative grounded in retrieved documents) is unavailable.
"#,
            signal.instrument,
            signal.direction,
            signal.confidence * 100.0,
            signal.timestamp.format("%Y-%m-%d %H:%M:%S UTC"),
            signal.context.current_price,
            signal.context.grid_stress_index,
            if signal.context.grid_stress_index > 70.0 {
                "HIGH"
            } else {
                "NORMAL"
            },
            signal.context.temperature_anomaly,
            signal.context.recent_policy_events.join(", "),
            signal.direction.to_lowercase(),
            signal.confidence * 100.0,
            deterministic.grounding_context,
        );

        Explanation {
            signal_id: signal.id.clone(),
            reference_class: None,
            ensemble: None,
            bayesian_update: None,
            scenarios: Some(deterministic.scenarios),
            expected_value: Some(deterministic.expected_value),
            risk_assessment: Some(deterministic.risk_assessment),
            market_analysis: Some("Template-based analysis".to_string()),
            signal_drivers: None,
            risks: None,
            expected_outcome: None,
            citations: vec![],
            raw_text: text,
            confidence_score: 0.6,
            generated_at: Utc::now(),
        }
    }
}

impl Default for TemplateEngine {
    fn default() -> Self {
        Self::new()
    }
}
