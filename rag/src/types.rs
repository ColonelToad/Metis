use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(crate = "serde")]
pub struct TradingSignal {
    pub id: String,
    pub instrument: String,
    pub direction: String, // "LONG" or "SHORT"
    pub confidence: f64,
    #[serde(deserialize_with = "deserialize_timestamp")]
    pub timestamp: DateTime<Utc>,
    #[serde(default = "default_context")]
    pub context: TradingContext,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TradingContext {
    #[serde(default)]
    pub current_price: f64,
    #[serde(default)]
    pub grid_stress_index: f64,
    #[serde(default)]
    pub temperature_anomaly: f64,
    #[serde(default)]
    pub recent_policy_events: Vec<String>,
    #[serde(default = "default_region")]
    pub primary_region: String,
}

fn default_context() -> TradingContext {
    TradingContext {
        current_price: 0.0,
        grid_stress_index: 50.0,
        temperature_anomaly: 0.0,
        recent_policy_events: vec![],
        primary_region: "ERCOT".to_string(),
    }
}

fn default_region() -> String {
    "ERCOT".to_string()
}

/// Custom deserializer that handles both string and DateTime timestamps
fn deserialize_timestamp<'de, D>(deserializer: D) -> Result<DateTime<Utc>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    use serde::de;

    struct TimestampVisitor;

    impl<'de> serde::de::Visitor<'de> for TimestampVisitor {
        type Value = DateTime<Utc>;

        fn expecting(&self, formatter: &mut std::fmt::Formatter) -> std::fmt::Result {
            formatter.write_str("a timestamp string (ISO 8601) or DateTime")
        }

        fn visit_str<E>(self, value: &str) -> Result<DateTime<Utc>, E>
        where
            E: de::Error,
        {
            DateTime::parse_from_rfc3339(value)
                .map(|dt| dt.with_timezone(&Utc))
                .or_else(|_| {
                    // Try parsing as just date+time without timezone
                    chrono::NaiveDateTime::parse_from_str(value, "%Y-%m-%dT%H:%M:%S")
                        .map(|ndt| DateTime::<Utc>::from_naive_utc_and_offset(ndt, Utc))
                })
                .map_err(E::custom)
        }

        fn visit_string<E>(self, value: String) -> Result<DateTime<Utc>, E>
        where
            E: de::Error,
        {
            self.visit_str(&value)
        }
    }

    deserializer.deserialize_string(TimestampVisitor)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Explanation {
    pub signal_id: String,

    // 8-Step Framework Fields
    /// Step 1: Reference class lookup from historical data
    pub reference_class: Option<ReferenceClassData>,
    /// Step 2: Ensemble aggregation with weighted sources
    pub ensemble: Option<EnsembleData>,
    /// Step 3: Bayesian update of probabilities
    pub bayesian_update: Option<BayesianData>,
    /// Step 4: Alternative scenarios with probabilities
    pub scenarios: Option<Vec<ScenarioData>>,
    /// Step 5: Expected value and risk-adjusted returns
    pub expected_value: Option<ExpectedValueData>,
    /// Step 6: Risk assessment and tail events
    pub risk_assessment: Option<RiskAssessmentData>,

    // Legacy fields (deprecated but kept for backwards compatibility)
    pub market_analysis: Option<String>,
    pub signal_drivers: Option<String>,
    pub risks: Option<String>,
    pub expected_outcome: Option<String>,

    pub citations: Vec<Citation>,
    pub raw_text: String,
    pub confidence_score: f64,
    pub generated_at: DateTime<Utc>,
}

/// Step 1: Reference Class - Historical analogs for base rates
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReferenceClassData {
    /// Name of the reference class (e.g. "Polar Vortex Cold Snap")
    pub class_name: String,
    /// Historical base rate (e.g., 0.75 = 75% of similar events matched thesis)
    pub base_rate: f64,
    /// Number of historical examples in this class
    pub sample_size: usize,
    /// Explanation of why this reference class applies
    pub reasoning: String,
}

/// Step 2: Ensemble Aggregation - Multiple signal sources
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EnsembleComponent {
    /// Source name (e.g. "ECMWF", "Grid Stress Index", "Technical Basis")
    pub source: String,
    /// Signal value in [-1, 1] range (strongly bearish to bullish)
    pub signal: f64,
    /// Confidence in this signal [0, 1]
    pub confidence: f64,
    /// Weight of this source in final ensemble [0, 1]
    pub weight: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EnsembleData {
    /// Individual components
    pub components: Vec<EnsembleComponent>,
    /// Final aggregated signal in [-1, 1]
    pub final_signal: f64,
    /// Agreement strength among sources [0, 1]
    pub agreement: f64,
}

/// Step 3: Bayesian Update - Prior → Posterior probability
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BayesianData {
    /// Prior probability from reference class
    pub prior: f64,
    /// Likelihood ratio of evidence
    pub likelihood_ratio: f64,
    /// Updated probability after incorporating new evidence
    pub posterior: f64,
    /// Key evidence that shifted the posterior
    pub evidence_summary: String,
}

/// Step 4: Scenario - Alternative market outcomes
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScenarioData {
    /// Scenario name (e.g. "Rapid Cold Snap", "Mild Winter")
    pub name: String,
    /// Probability of this scenario [0, 1]
    pub probability: f64,
    /// Expected price movement in this scenario (e.g., +15% or -8%)
    pub payoff: f64,
    /// Lower bound of possible outcomes
    pub payoff_min: f64,
    /// Upper bound of possible outcomes
    pub payoff_max: f64,
    /// Description of how this scenario unfolds
    pub description: String,
}

/// Step 5: Expected Value - Quantified risk-adjusted return
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExpectedValueData {
    /// Expected return across all scenarios (weighted sum)
    pub expected_return: f64,
    /// Standard deviation of returns across scenarios
    pub volatility: f64,
    /// Sharpe ratio (expected_return / volatility)
    pub sharpe_ratio: f64,
    /// Optimal Kelly position sizing as % of portfolio
    pub kelly_position_size: f64,
    /// Summary interpretation
    pub interpretation: String,
}

/// Step 6: Risk Assessment - Tail risks and worst cases
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskAssessmentData {
    /// Worst case scenario payoff
    pub worst_case: f64,
    /// Probability of worst case
    pub worst_case_probability: f64,
    /// Recovery time from worst case (in days)
    pub recovery_days: Option<usize>,
    /// Black swan probability (catastrophic event outside models)
    pub tail_risk_probability: f64,
    /// Points of concentration/single factor dominance
    pub concentration_risks: Vec<String>,
    /// Liquidity and execution risks
    pub liquidity_assessment: String,
    /// Risk checklist items (✓ or ✗)
    pub risk_checklist: Vec<(String, bool)>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Citation {
    pub doc_id: String,
    pub title: String,
    pub source: String,
    pub excerpt: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Document {
    pub id: String,
    pub title: String,
    pub content: String,
    pub source: String,
    pub category: String,
    pub timestamp: DateTime<Utc>,
}

#[derive(Debug, Clone)]
pub struct DocumentChunk {
    pub doc_id: String,
    pub content: String,
    pub embedding: Vec<f32>,
    pub metadata: serde_json::Value,
}
