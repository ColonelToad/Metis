use crate::orderbook::Side;
use anyhow::Result;
use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};
use tracing::info;

/// Parent order representing the full trading signal
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParentOrder {
    pub order_id: String,
    pub symbol: String,
    pub side: Side,
    pub quantity: f64,
    pub start_time: DateTime<Utc>,
    pub end_time: DateTime<Utc>,
    pub algo: ExecutionAlgo,
}

/// Execution algorithm type
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ExecutionAlgo {
    TWAP,
    VWAP,
    POV { target_participation: f64 }, // Percentage of Volume
    Arrival,                           // Minimize arrival price slippage
}

/// Child order sliced from parent
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChildOrder {
    pub child_id: String,
    pub parent_id: String,
    pub symbol: String,
    pub side: Side,
    pub quantity: f64,
    pub limit_price: Option<f64>,
    pub submit_time: DateTime<Utc>,
    pub status: OrderStatus,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum OrderStatus {
    Pending,
    Submitted,
    PartiallyFilled { filled_qty: f64, avg_price: f64 },
    Filled { avg_price: f64 },
    Cancelled,
    Rejected { reason: String },
}

/// Fill event from execution
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Fill {
    pub child_id: String,
    pub price: f64,
    pub quantity: f64,
    pub timestamp: DateTime<Utc>,
}

/// TWAP (Time-Weighted Average Price) execution algorithm
pub struct TwapExecutor {
    slice_duration: Duration,
}

impl TwapExecutor {
    pub fn new(slice_duration_secs: i64) -> Self {
        Self {
            slice_duration: Duration::seconds(slice_duration_secs),
        }
    }

    /// Generate child orders by slicing parent uniformly across time
    pub fn generate_child_orders(&self, parent: &ParentOrder) -> Result<Vec<ChildOrder>> {
        let total_duration = parent.end_time - parent.start_time;
        let num_slices =
            (total_duration.num_seconds() / self.slice_duration.num_seconds()) as usize;

        if num_slices == 0 {
            anyhow::bail!("Execution window too short for slicing");
        }

        let quantity_per_slice = parent.quantity / num_slices as f64;
        let mut children = Vec::new();

        for i in 0..num_slices {
            let submit_time = parent.start_time + self.slice_duration * i as i32;

            children.push(ChildOrder {
                child_id: format!("{}-{}", parent.order_id, i),
                parent_id: parent.order_id.clone(),
                symbol: parent.symbol.clone(),
                side: parent.side,
                quantity: quantity_per_slice,
                limit_price: None, // Market order for simplicity
                submit_time,
                status: OrderStatus::Pending,
            });
        }

        info!(
            "Generated {} TWAP slices for parent {} ({} per slice)",
            num_slices, parent.order_id, quantity_per_slice
        );

        Ok(children)
    }

    /// Calculate execution quality metrics
    pub fn calculate_metrics(
        &self,
        parent: &ParentOrder,
        fills: &[Fill],
        benchmark_price: f64,
    ) -> ExecutionMetrics {
        let total_filled_qty: f64 = fills.iter().map(|f| f.quantity).sum();
        let total_cost: f64 = fills.iter().map(|f| f.price * f.quantity).sum();
        let avg_fill_price = if total_filled_qty > 0.0 {
            total_cost / total_filled_qty
        } else {
            0.0
        };

        let signed_diff = match parent.side {
            Side::Bid => benchmark_price - avg_fill_price, // positive = paid less than benchmark (favorable)
            Side::Ask => avg_fill_price - benchmark_price, // positive = received more than benchmark (favorable)
        };

        // Signed: positive = execution beat the benchmark, negative = execution
        // was worse than the benchmark, consistent regardless of side. Magnitude:
        // always non-negative, "how far from benchmark" without direction. Both
        // are legitimate metrics for different questions ("did I do well" vs
        // "how much did this cost") — this used to only expose the magnitude.
        let signed_slippage_bps = (signed_diff / benchmark_price) * 10000.0;
        let slippage_bps = signed_slippage_bps.abs();

        ExecutionMetrics {
            parent_id: parent.order_id.clone(),
            target_quantity: parent.quantity,
            filled_quantity: total_filled_qty,
            avg_fill_price,
            benchmark_price,
            slippage_bps,
            signed_slippage_bps,
            completion_rate: total_filled_qty / parent.quantity,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionMetrics {
    pub parent_id: String,
    pub target_quantity: f64,
    pub filled_quantity: f64,
    pub avg_fill_price: f64,
    pub benchmark_price: f64,
    /// Magnitude only, always >= 0. "How far from benchmark, regardless of direction."
    pub slippage_bps: f64,
    /// Signed: positive = execution beat the benchmark, negative = it didn't.
    /// Consistent sign meaning across both sides (unlike raw price difference).
    pub signed_slippage_bps: f64,
    pub completion_rate: f64,
}

/// VWAP execution algorithm (simplified version)
pub struct VwapExecutor {
    historical_volume_profile: Vec<f64>, // Hourly volume distribution
}

impl VwapExecutor {
    pub fn new(volume_profile: Vec<f64>) -> Self {
        Self {
            historical_volume_profile: volume_profile,
        }
    }

    /// Generate child orders weighted by historical volume
    pub fn generate_child_orders(&self, parent: &ParentOrder) -> Result<Vec<ChildOrder>> {
        let total_duration = parent.end_time - parent.start_time;
        let num_slices = self.historical_volume_profile.len().min(
            (total_duration.num_seconds() / 3600) as usize, // Hourly slices
        );

        let total_volume_weight: f64 = self.historical_volume_profile.iter().take(num_slices).sum();
        let mut children = Vec::new();

        for i in 0..num_slices {
            let volume_weight = self.historical_volume_profile[i] / total_volume_weight;
            let slice_quantity = parent.quantity * volume_weight;
            let submit_time = parent.start_time + Duration::hours(i as i64);

            children.push(ChildOrder {
                child_id: format!("{}-{}", parent.order_id, i),
                parent_id: parent.order_id.clone(),
                symbol: parent.symbol.clone(),
                side: parent.side,
                quantity: slice_quantity,
                limit_price: None,
                submit_time,
                status: OrderStatus::Pending,
            });
        }

        info!(
            "Generated {} VWAP slices for parent {}",
            num_slices, parent.order_id
        );

        Ok(children)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_twap_slicing() {
        let parent = ParentOrder {
            order_id: "TEST-001".to_string(),
            symbol: "NG:CME".to_string(),
            side: Side::Bid,
            quantity: 100.0,
            start_time: Utc::now(),
            end_time: Utc::now() + Duration::minutes(15),
            algo: ExecutionAlgo::TWAP,
        };

        let executor = TwapExecutor::new(180); // 3-minute slices
        let children = executor.generate_child_orders(&parent).unwrap();

        assert_eq!(children.len(), 5); // 15 min / 3 min = 5 slices
        assert_eq!(children[0].quantity, 20.0); // 100 / 5 = 20 per slice
    }

    #[test]
    fn test_execution_metrics() {
        let parent = ParentOrder {
            order_id: "TEST-002".to_string(),
            symbol: "NG:CME".to_string(),
            side: Side::Bid,
            quantity: 100.0,
            start_time: Utc::now(),
            end_time: Utc::now() + Duration::minutes(15),
            algo: ExecutionAlgo::TWAP,
        };

        let fills = vec![
            Fill {
                child_id: "TEST-002-0".to_string(),
                price: 2.505,
                quantity: 50.0,
                timestamp: Utc::now(),
            },
            Fill {
                child_id: "TEST-002-1".to_string(),
                price: 2.510,
                quantity: 50.0,
                timestamp: Utc::now(),
            },
        ];

        let executor = TwapExecutor::new(180);
        let metrics = executor.calculate_metrics(&parent, &fills, 2.500);

        assert_eq!(metrics.filled_quantity, 100.0);
        assert!((metrics.avg_fill_price - 2.5075).abs() < 0.001);
        assert!(metrics.slippage_bps > 0.0); // Bought above benchmark
    }
}
