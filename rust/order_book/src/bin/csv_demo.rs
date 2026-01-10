use order_book::{OrderBook, Side};
use std::env;
use std::fs::File;
use std::io;

#[derive(Default)]
struct Pnl {
    cash: f64,
    pos: f64,
    equity: f64,
    equity_hist: Vec<f64>,
}

impl Pnl {
    fn on_trade(&mut self, side: Side, px: f64, qty: f64) {
        match side {
            Side::Buy => { self.cash -= px * qty; self.pos += qty; }
            Side::Sell => { self.cash += px * qty; self.pos -= qty; }
        }
    }
    fn mark(&mut self, mid: f64) {
        self.equity = self.cash + self.pos * mid;
        self.equity_hist.push(self.equity);
    }
    fn max_drawdown(&self) -> f64 {
        let mut peak = f64::NEG_INFINITY;
        let mut max_dd = 0.0;
        for &e in &self.equity_hist {
            if e > peak { peak = e; }
            let dd = if peak.is_finite() { (peak - e).max(0.0) } else { 0.0 };
            if dd > max_dd { max_dd = dd; }
        }
        max_dd
    }
    fn sharpe(&self) -> f64 {
        if self.equity_hist.len() < 2 { return 0.0; }
        let mut rets = Vec::with_capacity(self.equity_hist.len()-1);
        for w in self.equity_hist.windows(2) {
            let p = w[0]; let c = w[1];
            if p != 0.0 { rets.push((c - p) / p); }
        }
        if rets.is_empty() { return 0.0; }
        let mean = rets.iter().copied().sum::<f64>() / (rets.len() as f64);
        let var = rets.iter().map(|r| (r - mean)*(r - mean)).sum::<f64>() / (rets.len() as f64);
        let std = var.max(0.0).sqrt();
        if std == 0.0 { 0.0 } else { mean / std * (rets.len() as f64).sqrt() }
    }
}

fn usage() {
    eprintln!("Usage: csv_demo --features <path> [--signal <col>] [--price <col>] [--qty <f>] [--tick <f>] [--thr <f>]");
}

fn main() -> anyhow::Result<()> {
    // Args
    let args: Vec<String> = env::args().collect();
    let mut features_path: Option<String> = None;
    let mut signal_col: Option<String> = None;
    let mut price_col: Option<String> = None;
    let mut qty: f64 = 1.0;
    let mut tick: f64 = 0.001;
    let mut thr: f64 = 0.0; // trigger if signal > thr or < -thr; default act on any nonzero

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--features" => { i+=1; if i<args.len() { features_path = Some(args[i].clone()); } }
            "--signal" => { i+=1; if i<args.len() { signal_col = Some(args[i].clone()); } }
            "--price" => { i+=1; if i<args.len() { price_col = Some(args[i].clone()); } }
            "--qty" => { i+=1; if i<args.len() { qty = args[i].parse().unwrap_or(1.0); } }
            "--tick" => { i+=1; if i<args.len() { tick = args[i].parse().unwrap_or(0.001); } }
            "--thr" => { i+=1; if i<args.len() { thr = args[i].parse().unwrap_or(0.0); } }
            _ => {}
        }
        i+=1;
    }
    let features_path = match features_path { Some(p) => p, None => { usage(); return Err(anyhow::anyhow!("missing --features")); } };

    // CSV reader
    let file = File::open(&features_path)?;
    let mut rdr = csv::Reader::from_reader(file);
    let headers = rdr.headers()?.clone();

    // Determine column indices
    let price_colname = price_col.unwrap_or_else(|| {
        // fallbacks
        let cands = ["price","close","settle","last","Adj Close","adj_close"];
        cands.iter().find(|c| headers.iter().any(|h| h.eq_ignore_ascii_case(c))).unwrap_or(&"close").to_string()
    });
    let signal_colname = signal_col.unwrap_or_else(|| {
        let cands = ["signal","model_signal","momentum"];
        cands.iter().find(|c| headers.iter().any(|h| h.eq_ignore_ascii_case(c))).unwrap_or(&"signal").to_string()
    });

    let price_idx = headers.iter().position(|h| h.eq_ignore_ascii_case(&price_colname))
        .ok_or_else(|| anyhow::anyhow!(format!("price column '{}' not found", price_colname)))?;
    let signal_idx = headers.iter().position(|h| h.eq_ignore_ascii_case(&signal_colname));

    let mut ob = OrderBook::new(tick);
    let mut pnl = Pnl::default();
    let mut prev_price: Option<f64> = None;

    // iterate records
    for rec in rdr.records() {
        let rec = rec?;
        let p: f64 = match rec.get(price_idx).and_then(|s| s.parse::<f64>().ok()) {
            Some(v) => v,
            None => continue,
        };
        // seed book around price if empty or stale
        let mid = match (ob.best_bid(), ob.best_ask()) { (Some(bb), Some(ba)) => (bb+ba)/2.0, _ => f64::NAN };
        if !mid.is_finite() || (mid - p).abs() > 5.0 * tick {
            ob = OrderBook::new(tick);
        }
        for i in 1..=2 {
            ob.submit_limit(Side::Sell, p + (i as f64)*tick, 5.0);
            ob.submit_limit(Side::Buy,  p - (i as f64)*tick, 5.0);
        }

        // compute signal
        let sig_val = match signal_idx.and_then(|idx| rec.get(idx)).and_then(|s| s.parse::<f64>().ok()) {
            Some(v) => v,
            None => {
                // fallback: simple momentum from price
                if let Some(prev) = prev_price { (p - prev).signum() } else { 0.0 }
            }
        };

        // place market order if signal triggers
        if sig_val > thr {
            let my_id = ob.submit_market(Side::Buy, qty);
            // collect my trades
            for t in ob.trades.iter().rev() {
                if t.buy_id == my_id { pnl.on_trade(Side::Buy, t.price, t.qty); } else { break; }
            }
        } else if sig_val < -thr {
            let my_id = ob.submit_market(Side::Sell, qty);
            for t in ob.trades.iter().rev() {
                if t.sell_id == my_id { pnl.on_trade(Side::Sell, t.price, t.qty); } else { break; }
            }
        }

        // mark to market
        let mid = match (ob.best_bid(), ob.best_ask()) { (Some(bb), Some(ba)) => (bb+ba)/2.0, _ => p };
        pnl.mark(mid);
        prev_price = Some(p);
    }

    // summary
    println!("trades={}, final_pos={:.3}, cash={:.2}, equity={:.2}", ob.trades.len(), pnl.pos, pnl.cash, pnl.equity);
    println!("max_drawdown={:.2}, sharpe={:.3}", pnl.max_drawdown(), pnl.sharpe());

    Ok(())
}
