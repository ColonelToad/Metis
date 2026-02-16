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
