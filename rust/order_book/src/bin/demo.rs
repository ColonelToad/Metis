use order_book::{OrderBook, Side};
use std::time::Duration;

fn main() {
    let mut ob = OrderBook::new(0.001);

    // Seed book
    ob.submit_limit(Side::Sell, 2.001, 5.0);
    ob.submit_limit(Side::Sell, 2.003, 5.0);
    ob.submit_limit(Side::Buy, 1.999, 5.0);
    ob.submit_limit(Side::Buy, 1.997, 5.0);

    // Simulate a simple momentum signal: buy when price rising
    let prices = vec![2.000, 2.001, 2.002, 2.004, 2.003, 2.002, 2.001];
    for w in prices.windows(3) {
        let p1 = w[0];
        let p2 = w[1];
        let p3 = w[2];
        if p3 > p2 && p2 > p1 {
            // uptrend
            ob.submit_market(Side::Buy, 1.0);
        } else if p3 < p2 && p2 < p1 {
            // downtrend
            ob.submit_market(Side::Sell, 1.0);
        }
        std::thread::sleep(Duration::from_millis(50));
    }

    println!("Trades: {}", ob.trades.len());
    for t in ob.trades.iter() {
        println!(
            "buy={} sell={} px={:.3} qty={:.3}",
            t.buy_id, t.sell_id, t.price, t.qty
        );
    }
}
