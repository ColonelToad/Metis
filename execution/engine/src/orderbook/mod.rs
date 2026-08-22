mod csv_parser;
use anyhow::Result;
use chrono::{DateTime, Utc};
pub use csv_parser::CsvTickParser;
use ordered_float::OrderedFloat;
use rustc_hash::FxHashMap;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use tracing::debug;

/// Price level in the order book (stored as ordered float for BTreeMap)
pub type Price = OrderedFloat<f64>;

/// Quantity at a price level
pub type Quantity = f64;

/// Side of the order book
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Side {
    Bid,
    Ask,
}

/// Market event from tick data
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MarketEvent {
    pub timestamp: DateTime<Utc>,
    pub event_type: EventType,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum EventType {
    Trade {
        price: f64,
        quantity: f64,
        side: Side,
    },
    Quote {
        bid_price: f64,
        bid_quantity: f64,
        ask_price: f64,
        ask_quantity: f64,
    },
    AddOrder {
        order_id: u64,
        side: Side,
        price: f64,
        quantity: f64,
    },
    CancelOrder {
        order_id: u64,
    },
}

/// Level 2 Order Book
pub struct OrderBook {
    /// Instrument identifier (e.g., "NG:CME")
    pub symbol: String,

    /// Bid side: price -> total quantity (sorted descending)
    bids: BTreeMap<Price, Quantity>,

    /// Ask side: price -> total quantity (sorted ascending)
    asks: BTreeMap<Price, Quantity>,

    /// Last update timestamp
    pub last_update: DateTime<Utc>,

    /// Order ID to (side, price, quantity) mapping for cancellations
    order_map: FxHashMap<u64, (Side, Price, Quantity)>,
}

impl OrderBook {
    pub fn new(symbol: String) -> Self {
        Self {
            symbol,
            bids: BTreeMap::new(),
            asks: BTreeMap::new(),
            last_update: Utc::now(),
            order_map: FxHashMap::default(),
        }
    }

    /// Process a market event and update the order book
    pub fn process_event(&mut self, event: MarketEvent) -> Result<()> {
        self.last_update = event.timestamp;

        match event.event_type {
            EventType::Trade {
                price,
                quantity,
                side: _,
            } => {
                debug!("Trade: {} {} @ {}", quantity, self.symbol, price);
                // Trades don't update the book directly in L2 data
                Ok(())
            }
            EventType::Quote {
                bid_price,
                bid_quantity,
                ask_price,
                ask_quantity,
            } => self.update_quote(bid_price, bid_quantity, ask_price, ask_quantity),
            EventType::AddOrder {
                order_id,
                side,
                price,
                quantity,
            } => self.add_order(order_id, side, price, quantity),
            EventType::CancelOrder { order_id } => self.cancel_order(order_id),
        }
    }

    fn update_quote(
        &mut self,
        bid_price: f64,
        bid_quantity: f64,
        ask_price: f64,
        ask_quantity: f64,
    ) -> Result<()> {
        // Replace top of book with new quote
        self.bids.clear();
        self.asks.clear();

        if bid_quantity > 0.0 {
            self.bids.insert(OrderedFloat(bid_price), bid_quantity);
        }

        if ask_quantity > 0.0 {
            self.asks.insert(OrderedFloat(ask_price), ask_quantity);
        }

        Ok(())
    }

    fn add_order(&mut self, order_id: u64, side: Side, price: f64, quantity: f64) -> Result<()> {
        let price = OrderedFloat(price);

        let book = match side {
            Side::Bid => &mut self.bids,
            Side::Ask => &mut self.asks,
        };

        *book.entry(price).or_insert(0.0) += quantity;
        self.order_map.insert(order_id, (side, price, quantity));

        Ok(())
    }

    fn cancel_order(&mut self, order_id: u64) -> Result<()> {
        if let Some((side, price, quantity)) = self.order_map.remove(&order_id) {
            let book = match side {
                Side::Bid => &mut self.bids,
                Side::Ask => &mut self.asks,
            };

            if let Some(level_qty) = book.get_mut(&price) {
                *level_qty -= quantity;
                if *level_qty <= 0.0 {
                    book.remove(&price);
                }
            }
        }

        Ok(())
    }

    /// Get best bid price and quantity
    pub fn best_bid(&self) -> Option<(f64, f64)> {
        self.bids.iter().next_back().map(|(p, q)| (p.0, *q))
    }

    /// Get best ask price and quantity
    pub fn best_ask(&self) -> Option<(f64, f64)> {
        self.asks.iter().next().map(|(p, q)| (p.0, *q))
    }

    /// Calculate mid price
    pub fn mid_price(&self) -> Option<f64> {
        match (self.best_bid(), self.best_ask()) {
            (Some((bid, _)), Some((ask, _))) => Some((bid + ask) / 2.0),
            _ => None,
        }
    }

    /// Calculate spread in basis points
    pub fn spread_bps(&self) -> Option<f64> {
        match (self.best_bid(), self.best_ask()) {
            (Some((bid, _)), Some((ask, _))) => {
                let mid = (bid + ask) / 2.0;
                Some((ask - bid) / mid * 10000.0)
            }
            _ => None,
        }
    }

    /// Get total depth at top N levels
    pub fn depth(&self, levels: usize) -> (f64, f64) {
        let bid_depth: f64 = self.bids.iter().rev().take(levels).map(|(_, q)| q).sum();
        let ask_depth: f64 = self.asks.iter().take(levels).map(|(_, q)| q).sum();
        (bid_depth, ask_depth)
    }

    /// Calculate VWAP for given quantity
    pub fn vwap(&self, side: Side, quantity: f64) -> Option<f64> {
        let levels = match side {
            Side::Bid => &self.bids,
            Side::Ask => &self.asks,
        };

        let mut remaining = quantity;
        let mut total_cost = 0.0;

        let iter: Box<dyn Iterator<Item = _>> = match side {
            Side::Bid => Box::new(levels.iter().rev()),
            Side::Ask => Box::new(levels.iter()),
        };

        for (price, qty) in iter {
            let take_qty = remaining.min(*qty);
            total_cost += price.0 * take_qty;
            remaining -= take_qty;

            if remaining <= 0.0 {
                break;
            }
        }

        if remaining > 0.0 {
            None // Not enough liquidity
        } else {
            Some(total_cost / quantity)
        }
    }

    /// Simulate filling `quantity` on `side` against current resting depth,
    /// taking whatever is available level by level (partial fills allowed —
    /// unlike `vwap`, which is all-or-nothing). Returns (filled, average
    /// price); avg is None only when nothing fills. Mirrors the C++ engine's
    /// OrderBook::simulate_fill so both engines report identical fills
    /// against identical books.
    pub fn simulate_fill(&self, side: Side, quantity: f64) -> (f64, Option<f64>) {
        if quantity <= 0.0 {
            return (0.0, None);
        }

        let levels = match side {
            Side::Bid => &self.bids,
            Side::Ask => &self.asks,
        };

        let mut remaining = quantity;
        let mut total_cost = 0.0;

        let iter: Box<dyn Iterator<Item = _>> = match side {
            // Bids are stored best-first already; rev() on the ascending map
            // walks from the highest bid down.
            Side::Bid => Box::new(levels.iter().rev()),
            Side::Ask => Box::new(levels.iter()),
        };

        for (price, qty) in iter {
            let take_qty = remaining.min(*qty);
            total_cost += price.0 * take_qty;
            remaining -= take_qty;

            if remaining <= 0.0 {
                break;
            }
        }

        let filled = quantity - remaining.max(0.0);
        if filled > 0.0 {
            (filled, Some(total_cost / filled))
        } else {
            (0.0, None)
        }
    }

    /// Get snapshot of top N levels for visualization
    pub fn snapshot(&self, levels: usize) -> BookSnapshot {
        BookSnapshot {
            symbol: self.symbol.clone(),
            timestamp: self.last_update,
            bids: self
                .bids
                .iter()
                .rev()
                .take(levels)
                .map(|(p, q)| (p.0, *q))
                .collect(),
            asks: self
                .asks
                .iter()
                .take(levels)
                .map(|(p, q)| (p.0, *q))
                .collect(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BookSnapshot {
    pub symbol: String,
    pub timestamp: DateTime<Utc>,
    pub bids: Vec<(f64, f64)>, // (price, quantity)
    pub asks: Vec<(f64, f64)>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_order_book_quote() {
        let mut book = OrderBook::new("NG:CME".to_string());

        let event = MarketEvent {
            timestamp: Utc::now(),
            event_type: EventType::Quote {
                bid_price: 2.500,
                bid_quantity: 100.0,
                ask_price: 2.505,
                ask_quantity: 150.0,
            },
        };

        book.process_event(event).unwrap();

        assert_eq!(book.best_bid(), Some((2.500, 100.0)));

        assert_eq!(book.best_ask(), Some((2.505, 150.0)));
        assert_eq!(book.mid_price(), Some(2.5025));

        let spread = book.spread_bps().unwrap();
        assert!((spread - 19.99).abs() < 0.1); // ~20 bps
    }

    #[test]
    fn test_vwap_calculation() {
        let mut book = OrderBook::new("NG:CME".to_string());

        // Add multiple levels
        book.add_order(1, Side::Ask, 2.505, 50.0).unwrap();
        book.add_order(2, Side::Ask, 2.510, 75.0).unwrap();
        book.add_order(3, Side::Ask, 2.515, 100.0).unwrap();

        // VWAP for 100 contracts: (50*2.505 + 50*2.510) / 100
        let vwap = book.vwap(Side::Ask, 100.0).unwrap();
        assert!((vwap - 2.5075).abs() < 0.001);
    }

    #[test]
    fn test_simulate_fill_exact_and_spanning() {
        let mut book = OrderBook::new("NG:CME".to_string());
        book.add_order(1, Side::Bid, 2.500, 100.0).unwrap();
        book.add_order(2, Side::Bid, 2.495, 50.0).unwrap();

        // Single level covers it
        let (filled, avg) = book.simulate_fill(Side::Bid, 60.0);
        assert_eq!(filled, 60.0);
        assert_eq!(avg, Some(2.500));

        // Spans two levels: best price first
        let (filled, avg) = book.simulate_fill(Side::Bid, 120.0);
        assert_eq!(filled, 120.0);
        let expected = (100.0 * 2.500 + 20.0 * 2.495) / 120.0;
        assert!((avg.unwrap() - expected).abs() < 1e-12);
    }

    #[test]
    fn test_simulate_fill_partial_when_short() {
        let mut book = OrderBook::new("NG:CME".to_string());
        book.add_order(3, Side::Ask, 2.505, 75.0).unwrap();

        let (filled, avg) = book.simulate_fill(Side::Ask, 200.0);
        assert_eq!(filled, 75.0);
        assert_eq!(avg, Some(2.505));
    }

    #[test]
    fn test_simulate_fill_empty_side_and_zero_qty() {
        let mut book = OrderBook::new("NG:CME".to_string());
        book.add_order(4, Side::Bid, 2.500, 10.0).unwrap();

        let (filled, avg) = book.simulate_fill(Side::Ask, 5.0);
        assert_eq!(filled, 0.0);
        assert_eq!(avg, None);

        let (filled, avg) = book.simulate_fill(Side::Bid, 0.0);
        assert_eq!(filled, 0.0);
        assert_eq!(avg, None);
    }
}
