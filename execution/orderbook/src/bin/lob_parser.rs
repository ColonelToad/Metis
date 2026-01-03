use anyhow::Result;
use orderbook::{OrderBook, CsvTickParser};
use std::path::PathBuf;
use tracing::{info, Level};
use clap::Parser;

#[derive(Parser)]
struct Args {
    #[arg(short, long)]
    input: PathBuf,
}

fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_max_level(Level::INFO)
        .init();

    let args = Args::parse();
    info!("Parsing tick data from {:?}", args.input);
    let events = CsvTickParser::parse_file(&args.input)?;
    info!("Parsed {} events", events.len());
    let mut book = OrderBook::new("NG:CME".to_string());
    for event in events {
        book.process_event(event)?;
    }
    // Print final book state
    if let (Some((bid, bid_qty)), Some((ask, ask_qty))) = (book.best_bid(), book.best_ask()) {
        info!("Final book state:");
        info!("  Best bid: ${:.4} x {}", bid, bid_qty);
        info!("  Best ask: ${:.4} x {}", ask, ask_qty);
        info!("  Mid: ${:.4}", book.mid_price().unwrap());
        info!("  Spread: {:.2} bps", book.spread_bps().unwrap());
    }
    Ok(())
}
