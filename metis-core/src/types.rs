//! Core data types for Metis trading system
//!
//! Defines signal types, direction enums, and timestamp utilities

use serde::{Deserialize, Serialize};
use std::fmt;

/// Trading direction
#[repr(i8)]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Direction {
    Long = 1,
    Short = -1,
    Neutral = 0,
}

impl fmt::Display for Direction {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            Direction::Long => write!(f, "LONG"),
            Direction::Short => write!(f, "SHORT"),
            Direction::Neutral => write!(f, "NEUTRAL"),
        }
    }
}

/// Instrument identifier
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct InstrumentId(pub u32);

/// Trading signal from ML model
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TradingSignal {
    /// Nanosecond timestamp (from Python or TSC)
    pub timestamp_ns: u64,
    
    /// Target instrument (e.g., 1 = NG futures)
    pub instrument: InstrumentId,
    
    /// Direction: Long, Short, Neutral
    pub direction: Direction,
    
    /// Confidence [0.0, 1.0]
    pub confidence: f64,
    
    /// Predicted horizon in minutes
    pub horizon_minutes: u32,
}

impl TradingSignal {
    #[inline(always)]
    pub fn new(
        timestamp_ns: u64,
        instrument: InstrumentId,
        direction: Direction,
        confidence: f64,
        horizon_minutes: u32,
    ) -> Self {
        Self {
            timestamp_ns,
            instrument,
            direction,
            confidence,
            horizon_minutes,
        }
    }
}

/// Climate observation
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ClimateSignal {
    pub timestamp_ns: u64,
    pub region: String,
    pub temperature_c: f32,
    pub humidity_pct: f32,
    pub wind_kmh: f32,
}

/// Grid/energy market observation
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GridSignal {
    pub timestamp_ns: u64,
    pub region: String,
    pub lmp_usd_per_mwh: f32,
    pub demand_mw: f32,
    pub renewable_pct: f32,
}

/// Policy/sentiment observation
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PolicySignal {
    pub timestamp_ns: u64,
    pub source: String,
    pub sentiment_score: f32,  // -1.0 (bearish) to +1.0 (bullish)
    pub relevance: f32,        // 0.0 to 1.0
}

/// Fused multi-modal signal
#[derive(Clone, Debug)]
pub struct FusedSignal {
    pub timestamp_ns: u64,
    pub climate: ClimateSignal,
    pub grid: GridSignal,
    pub policy: PolicySignal,
}

impl FusedSignal {
    #[inline(always)]
    pub fn new(climate: ClimateSignal, grid: GridSignal, policy: PolicySignal) -> Self {
        Self {
            timestamp_ns: climate.timestamp_ns,
            climate,
            grid,
            policy,
        }
    }
}

/// Order execution status
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OrderStatus {
    Pending,
    PartiallyFilled,
    Filled,
    Cancelled,
}

/// TWAP execution order
#[derive(Clone, Debug)]
pub struct TwapOrder {
    pub order_id: u64,
    pub instrument: InstrumentId,
    pub direction: Direction,
    pub total_qty: f64,
    pub child_orders: usize,
    pub duration_secs: u32,
    pub start_time_ns: u64,
    pub status: OrderStatus,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_direction_values() {
        assert_eq!(Direction::Long as i8, 1);
        assert_eq!(Direction::Short as i8, -1);
        assert_eq!(Direction::Neutral as i8, 0);
    }

    #[test]
    fn test_trading_signal_creation() {
        let signal = TradingSignal::new(
            1_000_000_000,
            InstrumentId(1),
            Direction::Long,
            0.85,
            60,
        );
        assert_eq!(signal.timestamp_ns, 1_000_000_000);
        assert_eq!(signal.confidence, 0.85);
    }
}
