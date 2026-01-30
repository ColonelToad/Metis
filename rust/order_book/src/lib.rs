use std::collections::{BTreeMap, VecDeque};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Clone, Debug)]
pub struct Order {
    pub id: u64,
    pub side: Side,
    pub kind: Kind,
    pub price: Option<f64>,
    pub qty: f64,
    pub ts: f64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Side {
    Buy,
    Sell,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Limit,
    Market,
}

#[derive(Clone, Debug)]
pub struct Trade {
    pub buy_id: u64,
    pub sell_id: u64,
    pub price: f64,
    pub qty: f64,
    pub ts: f64,
}

#[derive(Default)]
struct PriceLevel {
    queue: VecDeque<Order>,
}

pub struct OrderBook {
    tick_size: f64,
    bids: BTreeMap<i64, PriceLevel>, // descending keys via rev()
    asks: BTreeMap<i64, PriceLevel>, // ascending keys
    pub trades: Vec<Trade>,
    next_id: u64,
}

impl OrderBook {
    pub fn new(tick_size: f64) -> Self {
        Self {
            tick_size,
            bids: BTreeMap::new(),
            asks: BTreeMap::new(),
            trades: Vec::new(),
            next_id: 1,
        }
    }

    fn now_ts() -> f64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs_f64()
    }

    fn norm_price(&self, p: f64) -> f64 {
        (p / self.tick_size).round() * self.tick_size
    }

    fn price_key(&self, p: f64) -> i64 {
        (p / self.tick_size).round() as i64
    }
    fn key_to_price(&self, k: i64) -> f64 {
        (k as f64) * self.tick_size
    }

    pub fn best_bid(&self) -> Option<f64> {
        self.bids.keys().rev().next().map(|k| self.key_to_price(*k))
    }
    pub fn best_ask(&self) -> Option<f64> {
        self.asks.keys().next().map(|k| self.key_to_price(*k))
    }

    pub fn submit_limit(&mut self, side: Side, price: f64, qty: f64) -> u64 {
        let id = self.next_id;
        self.next_id += 1;
        let price = self.norm_price(price);
        let key = self.price_key(price);
        let ts = Self::now_ts();
        let ord = Order {
            id,
            side,
            kind: Kind::Limit,
            price: Some(price),
            qty,
            ts,
        };
        match side {
            Side::Buy => self.bids.entry(key).or_default().queue.push_back(ord),
            Side::Sell => self.asks.entry(key).or_default().queue.push_back(ord),
        }
        self.match_crossed();
        id
    }

    pub fn submit_market(&mut self, side: Side, qty: f64) -> u64 {
        let id = self.next_id;
        self.next_id += 1;
        let ts = Self::now_ts();
        let mut ord = Order {
            id,
            side,
            kind: Kind::Market,
            price: None,
            qty,
            ts,
        };
        self.execute_market(&mut ord);
        id
    }

    pub fn cancel(&mut self, id: u64) -> bool {
        // Linear scan cancel (fine for demo)
        for map in [&mut self.bids, &mut self.asks] {
            let mut empty_prices: Vec<i64> = Vec::new();
            for (price, level) in map.iter_mut() {
                if let Some(pos) = level.queue.iter().position(|o| o.id == id) {
                    level.queue.remove(pos);
                    if level.queue.is_empty() {
                        empty_prices.push(*price);
                    }
                    return true;
                }
            }
            for p in empty_prices {
                map.remove(&p);
            }
        }
        false
    }

    fn crossed(&self) -> bool {
        match (self.best_bid(), self.best_ask()) {
            (Some(bb), Some(ba)) => bb >= ba,
            _ => false,
        }
    }

    fn pop_best(&mut self, side: Side) -> Option<(i64, Order)> {
        match side {
            Side::Sell => {
                let key = *self.asks.keys().next()?;
                let level = self.asks.get_mut(&key).unwrap();
                let ord = level.queue.front()?.clone();
                Some((key, ord))
            }
            Side::Buy => {
                let key = *self.bids.keys().rev().next()?;
                let level = self.bids.get_mut(&key).unwrap();
                let ord = level.queue.front()?.clone();
                Some((key, ord))
            }
        }
    }

    fn consume_best(&mut self, side: Side) {
        match side {
            Side::Sell => {
                let key = *self.asks.keys().next().unwrap();
                let level = self.asks.get_mut(&key).unwrap();
                level.queue.pop_front();
                if level.queue.is_empty() {
                    self.asks.remove(&key);
                }
            }
            Side::Buy => {
                let key = *self.bids.keys().rev().next().unwrap();
                let level = self.bids.get_mut(&key).unwrap();
                level.queue.pop_front();
                if level.queue.is_empty() {
                    self.bids.remove(&key);
                }
            }
        }
    }

    fn match_crossed(&mut self) {
        while self.crossed() {
            let (buy_key, mut buy) = self.pop_best(Side::Buy).unwrap();
            let (sell_key, mut sell) = self.pop_best(Side::Sell).unwrap();
            let qty = buy.qty.min(sell.qty);
            let price = self.key_to_price(sell_key); // trade at maker price
            let ts = Self::now_ts();
            self.trades.push(Trade {
                buy_id: buy.id,
                sell_id: sell.id,
                price,
                qty,
                ts,
            });
            buy.qty -= qty;
            sell.qty -= qty;
            if buy.qty <= 1e-12 {
                self.consume_best(Side::Buy);
            } else {
                // put back updated order at head
                let level = self.bids.get_mut(&buy_key).unwrap();
                if let Some(front) = level.queue.front_mut() {
                    *front = buy;
                }
            }
            if sell.qty <= 1e-12 {
                self.consume_best(Side::Sell);
            } else {
                let level = self.asks.get_mut(&sell_key).unwrap();
                if let Some(front) = level.queue.front_mut() {
                    *front = sell;
                }
            }
        }
    }

    fn execute_market(&mut self, ord: &mut Order) {
        let opp = match ord.side {
            Side::Buy => Side::Sell,
            Side::Sell => Side::Buy,
        };
        while ord.qty > 1e-12 {
            let best = match opp {
                Side::Sell => self.pop_best(Side::Sell),
                Side::Buy => self.pop_best(Side::Buy),
            };
            let (best_key, mut best) = match best {
                Some(o) => o,
                None => break,
            };
            let qty = ord.qty.min(best.qty);
            let price = self.key_to_price(best_key);
            let ts = Self::now_ts();
            match ord.side {
                Side::Buy => self.trades.push(Trade {
                    buy_id: ord.id,
                    sell_id: best.id,
                    price,
                    qty,
                    ts,
                }),
                Side::Sell => self.trades.push(Trade {
                    buy_id: best.id,
                    sell_id: ord.id,
                    price,
                    qty,
                    ts,
                }),
            }
            ord.qty -= qty;
            best.qty -= qty;
            // update or consume best
            if best.qty <= 1e-12 {
                self.consume_best(opp);
            } else {
                let level = match opp {
                    Side::Sell => self.asks.get_mut(&best_key).unwrap(),
                    Side::Buy => self.bids.get_mut(&best_key).unwrap(),
                };
                if let Some(front) = level.queue.front_mut() {
                    *front = best;
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn match_basic() {
        let mut ob = OrderBook::new(0.001);
        let b = ob.submit_limit(Side::Buy, 2.0, 1.0);
        let s = ob.submit_limit(Side::Sell, 2.0, 1.0);
        assert_eq!(ob.trades.len(), 1);
        let t = &ob.trades[0];
        assert_eq!(t.qty, 1.0);
        assert_eq!(t.price, 2.0);
        assert_eq!(t.buy_id, b);
        assert_eq!(t.sell_id, s);
    }
}
