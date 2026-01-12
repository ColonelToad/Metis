//! TWAP/VWAP Execution Algorithms
//!
//! Time-weighted and volume-weighted average price execution
//! Splits orders into child orders over time/volume

use crate::types::Direction;

/// TWAP Executor: splits order into N children over T seconds
pub struct TwapExecutor {
    total_qty: f64,
    num_children: usize,
    duration_secs: u32,
    child_qty: f64,
    interval_secs: u32,
}

impl TwapExecutor {
    /// Create TWAP executor
    /// 
    /// # Arguments
    /// * `total_qty` - Total quantity to execute
    /// * `num_children` - Number of child orders
    /// * `duration_secs` - Total execution time
    pub fn new(total_qty: f64, num_children: usize, duration_secs: u32) -> Self {
        assert!(num_children > 0);
        let child_qty = total_qty / (num_children as f64);
        let interval_secs = duration_secs / (num_children as u32);
        
        Self {
            total_qty,
            num_children,
            duration_secs,
            child_qty,
            interval_secs,
        }
    }
    
    /// Get next child order timestamp
    #[inline(always)]
    pub fn next_child_time(&self, child_index: usize) -> u32 {
        if child_index == 0 {
            0
        } else {
            child_index as u32 * self.interval_secs
        }
    }
    
    /// Get child order quantity
    #[inline(always)]
    pub fn child_quantity(&self, child_index: usize) -> f64 {
        // Handle rounding: last child gets remainder
        if child_index == self.num_children - 1 {
            self.total_qty - (self.child_qty * (child_index as f64))
        } else {
            self.child_qty
        }
    }
}

/// Slippage calculator
pub struct SlippageCalculator {
    arrival_price: f64,
    bid_ask_spread_bps: f64,
}

impl SlippageCalculator {
    pub fn new(arrival_price: f64, bid_ask_spread_bps: f64) -> Self {
        Self {
            arrival_price,
            bid_ask_spread_bps,
        }
    }
    
    /// Calculate slippage for a fill
    /// 
    /// Slippage = (fill_price - arrival_price) * qty * direction
    #[inline(always)]
    pub fn slippage(&self, fill_price: f64, direction: Direction) -> f64 {
        let delta_bps = ((fill_price - self.arrival_price) / self.arrival_price) * 10000.0;
        
        match direction {
            Direction::Long => delta_bps,   // Positive = worse for buyer
            Direction::Short => -delta_bps,  // Negative = worse for seller
            Direction::Neutral => 0.0,
        }
    }
    
    /// Calculate implementation shortfall
    /// 
    /// IS = (arrival_price - execution_vwap) * qty (in bps)
    #[inline(always)]
    pub fn implementation_shortfall(arrival_price: f64, execution_vwap: f64) -> f64 {
        ((arrival_price - execution_vwap) / arrival_price) * 10000.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_twap_executor() {
        let executor = TwapExecutor::new(1000.0, 10, 100);
        
        assert_eq!(executor.child_qty, 100.0);
        assert_eq!(executor.interval_secs, 10);
        
        // Check child order quantities sum to total
        let sum: f64 = (0..10)
            .map(|i| executor.child_quantity(i))
            .sum();
        assert!((sum - 1000.0).abs() < 0.01);
    }

    #[test]
    fn test_slippage_buy() {
        let calc = SlippageCalculator::new(100.0, 2.0);
        
        // Buy at 100.5 when arrival was 100.0
        let slippage = calc.slippage(100.5, Direction::Long);
        assert!(slippage > 0.0);  // Positive = bad for buyer
    }

    #[test]
    fn test_slippage_sell() {
        let calc = SlippageCalculator::new(100.0, 2.0);
        
        // Sell at 99.5 when arrival was 100.0
        let slippage = calc.slippage(99.5, Direction::Short);
        assert!(slippage > 0.0);  // Positive = bad for seller
    }
}
