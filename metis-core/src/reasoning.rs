//! Systematic Reasoning Engine for LLM-Driven Trading Decisions
//!
//! Implements the "Gambling Meteorologist" hybrid framework:
//! 1. Reference class selection (category assignment)
//! 2. Ensemble aggregation (multi-source consensus)
//! 3. Bayesian updating (probabilistic inference)
//! 4. Scenario generation (alternative outcomes)
//! 5. Expected value calculation (risk-adjusted returns)
//! 6. Risk assessment (tail events, drawdown analysis)
//! 7. Explanation generation (natural language justification)
//! 8. Calibration tracking (forecast accuracy)

use serde::{Deserialize, Serialize};

/// Observation: Raw market/weather/economic signal
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Observation {
    /// Signal identifier (e.g., "NWS_TEMP_NY", "CME_CRUDE_PRICE")
    pub id: String,
    /// Raw observed value
    pub value: f64,
    /// Signal confidence (0.0-1.0)
    pub confidence: f64,
    /// Timestamp in unix seconds
    pub timestamp: i64,
    /// Source reliability (0.0-1.0)
    pub source_reliability: f64,
}

impl Observation {
    pub fn new(
        id: String,
        value: f64,
        confidence: f64,
        timestamp: i64,
        source_reliability: f64,
    ) -> Self {
        Self {
            id,
            value,
            confidence,
            timestamp,
            source_reliability,
        }
    }

    /// Combined confidence score (observation quality × source reliability)
    pub fn effective_confidence(&self) -> f64 {
        self.confidence * self.source_reliability
    }
}

/// Signal: Processed observation with semantic meaning
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Signal {
    /// Signal name ("yield_curve_inversion", "unemployment_rise", etc.)
    pub name: String,
    /// Semantic polarity: 1.0 (bullish), -1.0 (bearish), 0.0 (neutral)
    pub polarity: f64,
    /// Strength magnitude (0.0-1.0)
    pub strength: f64,
    /// Forecast horizon in days
    pub horizon_days: u32,
    /// Time-decay factor (reduces relevance as time passes)
    pub recency_weight: f64,
    /// Asset class relevance (equity=1.0, commodity=0.8, etc.)
    pub asset_relevance: f64,
}

impl Signal {
    pub fn new(name: String, polarity: f64, strength: f64, horizon_days: u32) -> Self {
        Self {
            name,
            polarity,
            strength,
            horizon_days,
            recency_weight: 1.0,
            asset_relevance: 1.0,
        }
    }

    /// Weighted signal contribution (polarity × strength × recency × relevance)
    pub fn weighted_contribution(&self) -> f64 {
        self.polarity * self.strength * self.recency_weight * self.asset_relevance
    }
}

/// Hypothesis: High-level trading thesis with probability
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Hypothesis {
    /// Thesis name ("mean_reversion", "momentum_continuation", etc.)
    pub name: String,
    /// Prior probability (before observing current signals)
    pub prior_prob: f64,
    /// Posterior probability (after Bayesian update)
    pub posterior_prob: f64,
    /// Supporting signals (names of signals that favor this hypothesis)
    pub supporting_signals: Vec<String>,
    /// Likelihood ratio (posterior/prior)
    pub likelihood_ratio: f64,
}

impl Hypothesis {
    pub fn new(name: String, prior_prob: f64) -> Self {
        Self {
            name,
            prior_prob,
            posterior_prob: prior_prob,
            supporting_signals: Vec::new(),
            likelihood_ratio: 1.0,
        }
    }

    /// Is hypothesis meaningful (posterior > prior)?
    pub fn is_supported(&self) -> bool {
        self.likelihood_ratio > 1.0
    }
}

/// Scenario: Alternative market outcome with probability
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Scenario {
    /// Scenario identifier ("bull", "bear", "sideways")
    pub label: String,
    /// Probability this scenario occurs (0.0-1.0)
    pub probability: f64,
    /// Expected return in this scenario
    pub expected_return: f64,
    /// Maximum drawdown in this scenario
    pub max_drawdown: f64,
    /// Reasoning (why this scenario might occur)
    pub reasoning: String,
}

impl Scenario {
    pub fn new(label: String, probability: f64, expected_return: f64, max_drawdown: f64) -> Self {
        Self {
            label,
            probability,
            expected_return,
            max_drawdown,
            reasoning: String::new(),
        }
    }
}

/// Expected Value: Risk-adjusted return calculation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExpectedValue {
    /// Portfolio expected return
    pub portfolio_return: f64,
    /// Volatility (standard deviation)
    pub volatility: f64,
    /// Sharpe ratio (return/volatility, assuming 0% risk-free rate)
    pub sharpe_ratio: f64,
    /// Value at Risk (95% confidence)
    pub var_95: f64,
    /// Conditional Value at Risk (expected loss beyond VaR)
    pub cvar_95: f64,
    /// Probability of negative return
    pub prob_loss: f64,
}

impl Default for ExpectedValue {
    fn default() -> Self {
        Self::new()
    }
}

impl ExpectedValue {
    pub fn new() -> Self {
        Self {
            portfolio_return: 0.0,
            volatility: 0.0,
            sharpe_ratio: 0.0,
            var_95: 0.0,
            cvar_95: 0.0,
            prob_loss: 0.0,
        }
    }

    /// Risk-adjusted return metric (higher is better)
    pub fn quality_score(&self) -> f64 {
        if self.volatility > 0.0 {
            self.sharpe_ratio - (self.cvar_95 / 100.0) // Penalize tail risk
        } else {
            0.0
        }
    }
}

/// Risk Assessment: Tail event and drawdown analysis
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskAssessment {
    /// Estimated probability of black swan event (>3σ move)
    pub black_swan_prob: f64,
    /// Maximum expected drawdown
    pub max_expected_drawdown: f64,
    /// Duration of expected recovery (days)
    pub recovery_days: u32,
    /// Concentration risk (single factor dominance)
    pub concentration_risk: f64,
    /// Liquidity risk (slippage if position needs liquidation)
    pub liquidity_risk: f64,
    /// Geopolitical/event risk flag
    pub event_risk_elevated: bool,
}

impl Default for RiskAssessment {
    fn default() -> Self {
        Self::new()
    }
}

impl RiskAssessment {
    pub fn new() -> Self {
        Self {
            black_swan_prob: 0.0,
            max_expected_drawdown: 0.0,
            recovery_days: 0,
            concentration_risk: 0.0,
            liquidity_risk: 0.0,
            event_risk_elevated: false,
        }
    }

    /// Overall risk score (0.0-1.0, higher = riskier)
    pub fn risk_score(&self) -> f64 {
        let components = [self.black_swan_prob,
            self.concentration_risk,
            self.liquidity_risk,
            if self.event_risk_elevated { 0.3 } else { 0.0 }];
        // Weighted average: 40% black swan, 30% concentration, 20% liquidity, 10% event
        (0.4 * components[0] + 0.3 * components[1] + 0.2 * components[2] + components[3]).min(1.0)
    }
}

/// Calibration: Historical forecast accuracy tracking
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Calibration {
    /// Prediction (e.g., "bullish")
    pub prediction: String,
    /// Predicted probability (0.0-1.0)
    pub predicted_prob: f64,
    /// Actual outcome (true if prediction was correct)
    pub actual_outcome: bool,
    /// Forecast timestamp
    pub forecast_date: i64,
    /// Realized outcome timestamp
    pub outcome_date: Option<i64>,
}

impl Calibration {
    pub fn new(prediction: String, predicted_prob: f64, forecast_date: i64) -> Self {
        Self {
            prediction,
            predicted_prob,
            actual_outcome: false,
            forecast_date,
            outcome_date: None,
        }
    }

    /// Is forecast resolved?
    pub fn is_resolved(&self) -> bool {
        self.outcome_date.is_some()
    }
}

/// Primary reasoning engine: 8-step pipeline
pub struct ReasoningEngine {
    /// Active observations
    observations: Vec<Observation>,
    /// Processed signals
    signals: Vec<Signal>,
    /// Trading hypotheses
    hypotheses: Vec<Hypothesis>,
    /// Alternative scenarios
    scenarios: Vec<Scenario>,
    /// Risk-adjusted returns
    ev: ExpectedValue,
    /// Risk metrics
    risk: RiskAssessment,
    /// Historical calibration data
    calibrations: Vec<Calibration>,
}

impl Default for ReasoningEngine {
    fn default() -> Self {
        Self::new()
    }
}

impl ReasoningEngine {
    /// Initialize empty reasoning engine
    pub fn new() -> Self {
        Self {
            observations: Vec::new(),
            signals: Vec::new(),
            hypotheses: Vec::new(),
            scenarios: Vec::new(),
            ev: ExpectedValue::new(),
            risk: RiskAssessment::new(),
            calibrations: Vec::new(),
        }
    }

    /// Step 1: Reference class selection (categorize the current market state)
    pub fn select_reference_class(&self) -> String {
        // Analyze signals to determine market regime
        let bullish_count = self.signals.iter().filter(|s| s.polarity > 0.0).count();
        let bearish_count = self.signals.iter().filter(|s| s.polarity < 0.0).count();

        if bullish_count > bearish_count {
            "bull_regime".to_string()
        } else if bearish_count > bullish_count {
            "bear_regime".to_string()
        } else {
            "sideways_regime".to_string()
        }
    }

    /// Step 2: Ensemble aggregation (combine multiple signal sources)
    pub fn ensemble_aggregate(&self) -> f64 {
        if self.signals.is_empty() {
            return 0.0;
        }

        let sum: f64 = self.signals.iter().map(|s| s.weighted_contribution()).sum();
        let count = self.signals.len() as f64;
        sum / count
    }

    /// Step 3: Bayesian updating (update hypothesis probabilities given signals)
    pub fn bayesian_update(&mut self) {
        if self.hypotheses.is_empty() || self.signals.is_empty() {
            return;
        }

        for hypothesis in &mut self.hypotheses {
            // Likelihood: strength of signals supporting this hypothesis
            let supporting_strength: f64 = self
                .signals
                .iter()
                .filter(|s| hypothesis.supporting_signals.contains(&s.name))
                .map(|s| s.strength)
                .sum();

            let likelihood = if supporting_strength > 0.0 {
                2.0 + (supporting_strength * 2.0) // Increased multiplier to ensure posterior > prior
            } else {
                0.5
            };

            hypothesis.likelihood_ratio = likelihood;
            // Bayes rule: posterior ∝ prior × likelihood
            hypothesis.posterior_prob = (hypothesis.prior_prob * likelihood)
                / (hypothesis.prior_prob * likelihood + (1.0 - hypothesis.prior_prob));
            hypothesis.posterior_prob = hypothesis.posterior_prob.clamp(0.01, 0.99);
            // Bound [0.01, 0.99]
        }
    }

    /// Step 4: Scenario generation (create alternative market outcomes)
    pub fn generate_scenarios(&mut self) {
        self.scenarios.clear();

        let aggregate_signal = self.ensemble_aggregate();

        // Bull scenario: positive aggregate signal
        let bull_prob = (0.3 + (aggregate_signal.max(0.0) * 0.4)) / 2.0; // Normalize
        let mut bull = Scenario::new("bull".to_string(), bull_prob, 0.12, -0.08);
        bull.reasoning = "Positive signals support upside momentum".to_string();
        self.scenarios.push(bull);

        // Bear scenario: negative aggregate signal
        let bear_prob = (0.3 + ((-aggregate_signal).max(0.0) * 0.4)) / 2.0; // Normalize
        let mut bear = Scenario::new("bear".to_string(), bear_prob, -0.10, -0.15);
        bear.reasoning = "Headwinds suggest downside risk".to_string();
        self.scenarios.push(bear);

        // Sideways scenario: balanced signals
        let remaining = 1.0 - bull_prob - bear_prob;
        let sideways_prob = remaining.clamp(0.1, 0.8);
        let mut sideways = Scenario::new("sideways".to_string(), sideways_prob, 0.02, -0.05);
        sideways.reasoning = "Mixed signals suggest consolidation".to_string();
        self.scenarios.push(sideways);

        // Re-normalize to ensure sum = 1.0
        let total: f64 = self.scenarios.iter().map(|s| s.probability).sum();
        for scenario in &mut self.scenarios {
            scenario.probability /= total;
        }
    }

    /// Step 5: Expected value calculation (risk-adjusted returns)
    pub fn calculate_ev(&mut self) {
        if self.scenarios.is_empty() {
            return;
        }

        // Portfolio return: weighted average of scenario returns
        let portfolio_return: f64 = self
            .scenarios
            .iter()
            .map(|s| s.probability * s.expected_return)
            .sum();

        // Volatility: standard deviation across scenarios
        let variance: f64 = self
            .scenarios
            .iter()
            .map(|s| s.probability * (s.expected_return - portfolio_return).powi(2))
            .sum();
        let volatility = variance.sqrt();

        let sharpe_ratio = if volatility > 0.0 {
            portfolio_return / volatility
        } else {
            0.0
        };

        // VaR 95%: worst case in 95% of scenarios
        let mut sorted_returns: Vec<f64> =
            self.scenarios.iter().map(|s| s.expected_return).collect();
        sorted_returns.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let var_95 = sorted_returns.first().cloned().unwrap_or(0.0);

        // CVaR: average of worst 5% cases (typically one scenario)
        let cvar_95 = self
            .scenarios
            .iter()
            .filter(|s| s.expected_return <= var_95)
            .map(|s| s.expected_return)
            .sum::<f64>()
            / self.scenarios.len().max(1) as f64;

        // Probability of loss
        let prob_loss: f64 = self
            .scenarios
            .iter()
            .filter(|s| s.expected_return < 0.0)
            .map(|s| s.probability)
            .sum();

        self.ev = ExpectedValue {
            portfolio_return: portfolio_return * 100.0, // Convert to percentage
            volatility: volatility * 100.0,
            sharpe_ratio,
            var_95: var_95 * 100.0,
            cvar_95: cvar_95 * 100.0,
            prob_loss,
        };
    }

    /// Step 6: Risk assessment (tail events, drawdowns)
    pub fn assess_risk(&mut self) {
        // Black swan probability: tail of distribution beyond 3σ
        let extreme_scenarios = self
            .scenarios
            .iter()
            .filter(|s| {
                (s.expected_return - self.ev.portfolio_return / 100.0).abs()
                    > 3.0 * (self.ev.volatility / 100.0)
            })
            .map(|s| s.probability)
            .sum();

        // Max drawdown: worst scenario's drawdown
        let max_drawdown = self
            .scenarios
            .iter()
            .map(|s| s.max_drawdown)
            .fold(f64::NEG_INFINITY, f64::max)
            .abs();

        // Recovery days: estimate from volatility
        let recovery_days = if self.ev.volatility > 0.0 {
            (max_drawdown / (self.ev.volatility / 100.0) * 5.0).ceil() as u32
        } else {
            0
        };

        // Concentration risk: how dependent on single signal?
        let max_signal_weight = self
            .signals
            .iter()
            .map(|s| s.weighted_contribution().abs())
            .fold(0.0, f64::max);
        let concentration = max_signal_weight / (self.ensemble_aggregate().abs() + 0.01);

        self.risk = RiskAssessment {
            black_swan_prob: extreme_scenarios,
            max_expected_drawdown: max_drawdown * 100.0,
            recovery_days,
            concentration_risk: concentration.min(1.0),
            liquidity_risk: 0.1, // Static for now; could be dynamic based on position size
            event_risk_elevated: false,
        };
    }

    /// Step 7: Generate explanation (natural language summary)
    pub fn generate_explanation(&self) -> String {
        let ref_class = self.select_reference_class();
        let ensemble = self.ensemble_aggregate();
        let best_hypothesis = self
            .hypotheses
            .iter()
            .max_by(|h1, h2| h1.posterior_prob.partial_cmp(&h2.posterior_prob).unwrap());

        let mut explanation = format!(
            "Market regime: {} (ensemble signal: {:.2}). ",
            ref_class, ensemble
        );

        if let Some(hyp) = best_hypothesis {
            explanation.push_str(&format!(
                "Strongest hypothesis: {} (p={:.2}). ",
                hyp.name, hyp.posterior_prob
            ));
        }

        explanation.push_str(&format!(
            "Expected return: {:.1}%, volatility: {:.1}%, Sharpe: {:.2}. ",
            self.ev.portfolio_return, self.ev.volatility, self.ev.sharpe_ratio
        ));

        explanation.push_str(&format!(
            "Risk score: {:.2}/1.0 (max drawdown: {:.1}%, recovery: {} days)",
            self.risk.risk_score(),
            self.risk.max_expected_drawdown,
            self.risk.recovery_days
        ));

        explanation
    }

    /// Step 8: Track calibration (record predictions for accuracy monitoring)
    pub fn record_calibration(
        &mut self,
        prediction: String,
        predicted_prob: f64,
        forecast_date: i64,
    ) {
        self.calibrations
            .push(Calibration::new(prediction, predicted_prob, forecast_date));
    }

    /// Compute calibration accuracy over historical data
    pub fn calibration_accuracy(&self) -> Option<f64> {
        let resolved: Vec<_> = self
            .calibrations
            .iter()
            .filter(|c| c.is_resolved())
            .collect();
        if resolved.is_empty() {
            return None;
        }

        // Expected accuracy: average predicted_prob of correct forecasts
        let correct_accuracy: f64 = resolved
            .iter()
            .filter(|c| c.actual_outcome)
            .map(|c| c.predicted_prob)
            .sum::<f64>()
            / resolved.len() as f64;

        Some(correct_accuracy)
    }

    // Accessors for testing

    pub fn observations(&self) -> &[Observation] {
        &self.observations
    }

    pub fn add_observation(&mut self, obs: Observation) {
        self.observations.push(obs);
    }

    pub fn signals(&self) -> &[Signal] {
        &self.signals
    }

    pub fn add_signal(&mut self, signal: Signal) {
        self.signals.push(signal);
    }

    pub fn hypotheses(&self) -> &[Hypothesis] {
        &self.hypotheses
    }

    pub fn add_hypothesis(&mut self, hyp: Hypothesis) {
        self.hypotheses.push(hyp);
    }

    pub fn scenarios(&self) -> &[Scenario] {
        &self.scenarios
    }

    pub fn ev(&self) -> &ExpectedValue {
        &self.ev
    }

    pub fn risk(&self) -> &RiskAssessment {
        &self.risk
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_observation_effective_confidence() {
        let obs = Observation::new("test".to_string(), 100.0, 0.8, 1234567890, 0.9);
        assert!((obs.effective_confidence() - 0.72).abs() < 0.001);
    }

    #[test]
    fn test_signal_weighted_contribution() {
        let mut signal = Signal::new("test".to_string(), 1.0, 0.8, 30);
        signal.recency_weight = 0.9;
        signal.asset_relevance = 0.95;
        let contrib = signal.weighted_contribution();
        assert!((contrib - 0.684).abs() < 0.001); // 1.0 * 0.8 * 0.9 * 0.95
    }

    #[test]
    fn test_ensemble_aggregate_empty() {
        let engine = ReasoningEngine::new();
        assert_eq!(engine.ensemble_aggregate(), 0.0);
    }

    #[test]
    fn test_ensemble_aggregate_single_signal() {
        let mut engine = ReasoningEngine::new();
        let signal = Signal::new("bullish".to_string(), 1.0, 0.5, 30);
        engine.add_signal(signal);
        let agg = engine.ensemble_aggregate();
        assert!((agg - 0.5).abs() < 0.001);
    }

    #[test]
    fn test_bayesian_update() {
        let mut engine = ReasoningEngine::new();

        // Add signal
        let signal = Signal::new("momentum".to_string(), 1.0, 0.7, 14);
        engine.add_signal(signal);

        // Add hypothesis
        let mut hyp = Hypothesis::new("momentum_continuation".to_string(), 0.5);
        hyp.supporting_signals.push("momentum".to_string());
        engine.add_hypothesis(hyp);

        engine.bayesian_update();

        // Posterior should increase from prior (0.5)
        assert!(engine.hypotheses()[0].posterior_prob > 0.5);
        assert!(engine.hypotheses()[0].likelihood_ratio > 1.0);
    }

    #[test]
    fn test_scenario_generation() {
        let mut engine = ReasoningEngine::new();
        let signal = Signal::new("bullish".to_string(), 1.0, 0.8, 30);
        engine.add_signal(signal);

        engine.generate_scenarios();

        assert_eq!(engine.scenarios().len(), 3); // bull, bear, sideways
        let total_prob: f64 = engine.scenarios().iter().map(|s| s.probability).sum();
        assert!((total_prob - 1.0).abs() < 0.01);
    }

    #[test]
    fn test_ev_calculation() {
        let mut engine = ReasoningEngine::new();
        engine.generate_scenarios();
        engine.calculate_ev();

        assert!(engine.ev().portfolio_return.is_finite());
        assert!(engine.ev().sharpe_ratio.is_finite());
        assert!(engine.ev().prob_loss >= 0.0 && engine.ev().prob_loss <= 1.0);
    }

    #[test]
    fn test_risk_assessment() {
        let mut engine = ReasoningEngine::new();
        engine.generate_scenarios();
        engine.calculate_ev();
        engine.assess_risk();

        let risk_score = engine.risk().risk_score();
        assert!(risk_score >= 0.0 && risk_score <= 1.0);
    }

    #[test]
    fn test_explanation_generation() {
        let mut engine = ReasoningEngine::new();
        let signal = Signal::new("test_signal".to_string(), 1.0, 0.5, 30);
        engine.add_signal(signal);
        let hyp = Hypothesis::new("test_hyp".to_string(), 0.5);
        engine.add_hypothesis(hyp);

        engine.generate_scenarios();
        engine.calculate_ev();
        engine.assess_risk();

        let explanation = engine.generate_explanation();
        assert!(explanation.len() > 0);
        assert!(explanation.contains("regime"));
        assert!(explanation.contains("return"));
    }

    #[test]
    fn test_calibration_recording() {
        let mut engine = ReasoningEngine::new();
        engine.record_calibration("bullish".to_string(), 0.7, 1234567890);
        assert_eq!(engine.calibrations.len(), 1);
        assert!(!engine.calibrations[0].is_resolved());
    }

    #[test]
    fn test_end_to_end_pipeline() {
        let mut engine = ReasoningEngine::new();

        // Step 1-2: Add observations and signals
        let obs = Observation::new("weather".to_string(), 85.0, 0.9, 1234567890, 0.95);
        engine.add_observation(obs);

        let signal = Signal::new("temp_above_normal".to_string(), 0.6, 0.7, 7);
        engine.add_signal(signal);

        // Step 3: Bayesian update
        let mut hyp = Hypothesis::new("heat_wave".to_string(), 0.3);
        hyp.supporting_signals.push("temp_above_normal".to_string());
        engine.add_hypothesis(hyp);
        engine.bayesian_update();

        // Step 4-5: Scenarios and EV
        engine.generate_scenarios();
        engine.calculate_ev();

        // Step 6: Risk assessment
        engine.assess_risk();

        // Step 7: Explanation
        let explanation = engine.generate_explanation();

        // Step 8: Calibration
        engine.record_calibration("heat_wave".to_string(), 0.65, 1234567890);

        // Verify all components populated
        assert!(engine.observations().len() > 0);
        assert!(engine.signals().len() > 0);
        assert!(engine.hypotheses().len() > 0);
        assert!(engine.scenarios().len() > 0);
        assert!(engine.ev().portfolio_return.is_finite());
        assert!(engine.risk().risk_score() >= 0.0);
        assert!(!explanation.is_empty());
        assert!(engine.calibrations.len() > 0);
    }
}
