//! Bridges the RAG layer's `TradingSignal`/`TradingContext` to `engine`'s
//! deterministic `ReasoningEngine`, and translates the engine's output into
//! this crate's `ScenarioData`/`ExpectedValueData`/`RiskAssessmentData`.
//!
//! This exists because of a finding from the Phase 1/2 audit: the same
//! "Gambling Meteorologist" 8-step framework existed twice — once as real
//! math in `engine::reasoning`, once as a JSON schema an LLM was asked to
//! fill in from scratch. The live prompt had already quietly retreated from
//! asking for the full schema (probably because a small local model
//! couldn't reliably produce it), and the no-LLM fallback (`template.rs`)
//! never computed real numbers at all — it left every structured field as
//! `None`. This module makes the engine's math the single source of truth
//! for the structured fields; the LLM's job becomes writing prose about
//! numbers it's handed, not reconstructing them from nothing.
//!
//! Important caveat: the signal-to-Observation/Signal mapping below encodes
//! real domain assumptions (e.g. "higher grid stress is bullish for gas
//! prices," "warmer-than-normal anomaly is directionally significant") that
//! haven't been validated against the actual upstream Python model's
//! semantics — they're a reasonable starting point, not verified fact.
//! Worth checking the sign conventions against how the signal model
//! actually defines these fields before trusting this in anything live.

use crate::types::{ExpectedValueData, RiskAssessmentData, ScenarioData, TradingSignal};
use engine::reasoning::{Hypothesis, ReasoningEngine, Signal};

/// Computed output of the deterministic reasoning pass, ready to slot
/// directly into `Explanation`'s structured fields.
pub struct DeterministicReasoning {
    pub scenarios: Vec<ScenarioData>,
    pub expected_value: ExpectedValueData,
    pub risk_assessment: RiskAssessmentData,
    /// Plain-text summary of the computed numbers, meant to be handed to
    /// the LLM as grounding context so it narrates real numbers instead of
    /// inventing its own.
    pub grounding_context: String,
}

/// Run the deterministic reasoning pipeline against a trading signal's
/// context and return the computed, structured results.
pub fn compute(signal: &TradingSignal) -> DeterministicReasoning {
    let mut reasoning_engine = ReasoningEngine::new();
    let ctx = &signal.context;

    // --- Map TradingContext into Observations/Signals ---
    // Sign conventions here are a first-pass assumption (see module doc),
    // not validated domain knowledge.
    let temp_signal_polarity = (ctx.temperature_anomaly / 10.0).clamp(-1.0, 1.0);
    reasoning_engine.add_signal(Signal::new(
        "temperature_anomaly".to_string(),
        temp_signal_polarity,
        (ctx.temperature_anomaly.abs() / 10.0).clamp(0.0, 1.0),
        7,
    ));

    let grid_signal_polarity = ((ctx.grid_stress_index - 50.0) / 50.0).clamp(-1.0, 1.0);
    reasoning_engine.add_signal(Signal::new(
        "grid_stress".to_string(),
        grid_signal_polarity,
        (ctx.grid_stress_index / 100.0).clamp(0.0, 1.0),
        3,
    ));

    if !ctx.recent_policy_events.is_empty() {
        // Policy events are treated as adding uncertainty (a real, if
        // simplistic, choice) rather than scored bullish/bearish, since we
        // don't have per-event directionality here.
        reasoning_engine.add_signal(Signal::new(
            "policy_activity".to_string(),
            0.0,
            (ctx.recent_policy_events.len() as f64 / 5.0).clamp(0.0, 1.0),
            14,
        ));
    }

    // The signal's own stated direction becomes the hypothesis under test,
    // with its confidence as the prior.
    let hypothesis_name = if signal.direction.eq_ignore_ascii_case("LONG") {
        "long_thesis"
    } else {
        "short_thesis"
    };
    let mut hypothesis =
        Hypothesis::new(hypothesis_name.to_string(), signal.confidence.clamp(0.01, 0.99));
    hypothesis
        .supporting_signals
        .push("temperature_anomaly".to_string());
    hypothesis.supporting_signals.push("grid_stress".to_string());
    reasoning_engine.add_hypothesis(hypothesis);

    reasoning_engine.bayesian_update();
    reasoning_engine.generate_scenarios();
    reasoning_engine.calculate_ev();
    reasoning_engine.assess_risk();

    // --- Translate engine output into rag::types structures ---

    let scenarios: Vec<ScenarioData> = reasoning_engine
        .scenarios()
        .iter()
        .map(|s| ScenarioData {
            name: s.label.clone(),
            // engine::reasoning stores returns as fractions (e.g. 0.12);
            // ScenarioData's own doc comment expects percentage-style
            // numbers (e.g. +15.0 meaning 15%), so scale by 100 here.
            payoff: s.expected_return * 100.0,
            payoff_min: s.max_drawdown * 100.0,
            payoff_max: s.expected_return.max(0.0) * 100.0,
            probability: s.probability,
            description: s.reasoning.clone(),
        })
        .collect();

    let ev = reasoning_engine.ev();
    // Simplified continuous Kelly (mean/variance), clamped conservatively.
    // This is not a rigorous Kelly derivation against real win/loss odds —
    // ReasoningEngine models scenario-weighted returns, not discrete
    // win/loss probabilities, so this is a defensible approximation for a
    // rough sizing hint, not a precise position-sizing formula.
    let variance = (ev.volatility / 100.0).powi(2);
    let kelly = if variance > 0.0001 {
        ((ev.portfolio_return / 100.0) / variance).clamp(0.0, 0.25)
    } else {
        0.0
    };

    let expected_value = ExpectedValueData {
        expected_return: ev.portfolio_return,
        volatility: ev.volatility,
        sharpe_ratio: ev.sharpe_ratio,
        kelly_position_size: kelly,
        interpretation: format!(
            "Computed from {} scenarios: {:.1}% expected return, {:.1}% volatility, Sharpe {:.2}.",
            reasoning_engine.scenarios().len(),
            ev.portfolio_return,
            ev.volatility,
            ev.sharpe_ratio
        ),
    };

    let risk = reasoning_engine.risk();
    let worst_scenario = reasoning_engine
        .scenarios()
        .iter()
        .min_by(|a, b| a.expected_return.partial_cmp(&b.expected_return).unwrap());

    let risk_assessment = RiskAssessmentData {
        worst_case: worst_scenario
            .map(|s| s.expected_return * 100.0)
            .unwrap_or(-risk.max_expected_drawdown),
        worst_case_probability: worst_scenario.map(|s| s.probability).unwrap_or(0.0),
        recovery_days: Some(risk.recovery_days as usize),
        tail_risk_probability: risk.black_swan_prob,
        concentration_risks: if risk.concentration_risk > 0.5 {
            vec!["Single-signal concentration above 50%".to_string()]
        } else {
            vec![]
        },
        liquidity_assessment: if risk.liquidity_risk > 0.3 {
            "Elevated liquidity risk".to_string()
        } else {
            "Liquidity risk within normal range".to_string()
        },
        risk_checklist: vec![
            ("Event risk flagged".to_string(), risk.event_risk_elevated),
            (
                "Concentration risk > 50%".to_string(),
                risk.concentration_risk > 0.5,
            ),
            (
                "Black swan probability > 5%".to_string(),
                risk.black_swan_prob > 0.05,
            ),
        ],
    };

    let grounding_context = format!(
        "Computed scenarios (deterministic, not LLM-generated):\n{}\n\n\
         Expected value: {:.1}% return, {:.1}% volatility, Sharpe {:.2}, Kelly size {:.1}%.\n\
         Risk: {:.1}% black-swan probability, {:.1}% max expected drawdown, recovery ~{} days.",
        scenarios
            .iter()
            .map(|s| format!(
                "- {} (p={:.2}): {:+.1}% [{:+.1}% to {:+.1}%]",
                s.name, s.probability, s.payoff, s.payoff_min, s.payoff_max
            ))
            .collect::<Vec<_>>()
            .join("\n"),
        expected_value.expected_return,
        expected_value.volatility,
        expected_value.sharpe_ratio,
        expected_value.kelly_position_size * 100.0,
        risk_assessment.tail_risk_probability * 100.0,
        risk.max_expected_drawdown,
        risk.recovery_days,
    );

    DeterministicReasoning {
        scenarios,
        expected_value,
        risk_assessment,
        grounding_context,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::TradingContext;
    use chrono::Utc;

    fn sample_signal() -> TradingSignal {
        TradingSignal {
            id: "test".to_string(),
            instrument: "NG".to_string(),
            direction: "LONG".to_string(),
            confidence: 0.75,
            timestamp: Utc::now(),
            context: TradingContext {
                current_price: 3.0,
                grid_stress_index: 75.0,
                temperature_anomaly: 8.0,
                recent_policy_events: vec!["FERC Order".to_string()],
                primary_region: "ERCOT".to_string(),
            },
        }
    }

    #[test]
    fn produces_three_scenarios_summing_to_one() {
        let result = compute(&sample_signal());
        assert_eq!(result.scenarios.len(), 3);
        let total_prob: f64 = result.scenarios.iter().map(|s| s.probability).sum();
        assert!((total_prob - 1.0).abs() < 0.01);
    }

    #[test]
    fn expected_value_is_finite() {
        let result = compute(&sample_signal());
        assert!(result.expected_value.expected_return.is_finite());
        assert!(result.expected_value.sharpe_ratio.is_finite());
    }

    #[test]
    fn kelly_size_is_clamped_to_conservative_range() {
        let result = compute(&sample_signal());
        assert!(result.expected_value.kelly_position_size >= 0.0);
        assert!(result.expected_value.kelly_position_size <= 0.25);
    }

    #[test]
    fn grounding_context_is_nonempty() {
        let result = compute(&sample_signal());
        assert!(!result.grounding_context.is_empty());
        assert!(result.grounding_context.contains("Computed scenarios"));
    }
}
