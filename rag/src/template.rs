use crate::types::{Explanation, TradingSignal};
use chrono::Utc;

pub struct TemplateEngine;

impl TemplateEngine {
    pub fn new() -> Self {
        Self
    }

    pub fn generate(&self, signal: &TradingSignal) -> Explanation {
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

## Expected Outcome
Position expected to align with supply/demand fundamentals given current market conditions.

Note: This is a template-based explanation. Full chain-of-thought analysis unavailable.
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
        );

        Explanation {
            signal_id: signal.id.clone(),
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
