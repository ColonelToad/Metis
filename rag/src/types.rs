use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TradingSignal {
    pub id: String,
    pub instrument: String,
    pub direction: String, // "BUY" or "SELL"
    pub confidence: f64,
    pub timestamp: DateTime<Utc>,
    pub context: TradingContext,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TradingContext {
    pub current_price: f64,
    pub grid_stress_index: f64,
    pub temperature_anomaly: f64,
    pub recent_policy_events: Vec<String>,
    pub primary_region: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Explanation {
    pub signal_id: String,
    pub market_analysis: Option<String>,
    pub signal_drivers: Option<String>,
    pub risks: Option<String>,
    pub expected_outcome: Option<String>,
    pub citations: Vec<Citation>,
    pub raw_text: String,
    pub confidence_score: f64,
    pub generated_at: DateTime<Utc>,
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
