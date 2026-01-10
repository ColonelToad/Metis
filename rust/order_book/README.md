# Order Book (Rust)

Simple FIFO price-time order book with a demo and CSV-driven simulation.

## Build

```bash
cd rust/order_book
cargo build
```

## Demos

- Momentum demo with embedded price list:

```bash
cargo run --bin demo
```

- CSV-driven simulation with simple PnL:

```bash
# Using the provided sample
cargo run --bin csv_demo -- --features examples/features_sample.csv --qty 1.0 --tick 0.001 --thr 0.0

# With your own features file
cargo run --bin csv_demo -- --features path/to/your.csv --signal signal --price close --qty 1.0 --tick 0.001 --thr 0.2
```

Arguments:
- `--features`: path to CSV with at least a price column.
- `--price`: price column name (default tries close/price/settle/etc.).
- `--signal`: signal column name (default `signal`; if missing, momentum from price).
- `--qty`: order quantity per signal trigger (default 1.0).
- `--tick`: tick size in price units (default 0.001).
- `--thr`: threshold for acting on signal (default 0.0).

Outputs include total trades, final position, cash/equity, max drawdown, and a simple Sharpe computed on step returns.