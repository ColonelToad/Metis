# Metis

Metis is a quantitative research platform for climate-driven energy trading, targeting CME Henry Hub Natural Gas (NG) futures. It combines a Python data and signal pipeline, a Rust low-latency execution engine, and a Tauri desktop interface with LLM-powered signal explanations.

## Architecture

The system is organized into three layers that communicate through well-defined interfaces:

**Research & Signal Generation (Python)**
Data ingestion from 13+ sources feeds a feature engineering pipeline and LSTM hybrid model that produces directional signals on NG futures. Sources include EIA storage reports, FRED macroeconomic series, CME futures via Databento, NOAA/Open-Meteo weather, grid LMP prices across ISO regions, AIS vessel tracking, Congressional climate legislation, and Census building permits. Data is stored locally in SQLite with daily backups to Cloudflare R2.

**Execution Engine (Rust)**
A lock-free signal fusion layer aggregates climate, grid, and policy signals using `crossbeam` channels and atomic operations. A limit order book simulator (with CSV and PCAP ingestion) feeds TWAP/VWAP execution algorithms. A FIX protocol client handles market connectivity. `metis-core` exposes a PyO3 bridge so Python signals cross into Rust with minimal latency. SIMD vectorization and NUMA thread pinning are implemented for Windows and Linux targets.

**Interface & Explanation (Tauri + RAG)**
A Tauri 2.0 desktop application provides real-time dashboards across markets, grid status, climate data, policy, portfolio, and backtesting views. A RAG pipeline (LanceDB + sentence-transformers) indexes signal documentation and policy texts to support LLM-generated explanations of trading decisions.

```
Python signals → PyO3 bridge (metis-core)
              → lock-free fusion (crossbeam)
              → order book + execution algos
              → FIX protocol
              → RAG explanation pipeline → Tauri UI
```

## Status

| Component | Status |
|-----------|--------|
| Python data ingestion (13+ sources) | Active |
| Feature engineering & LSTM model | Active |
| Backtesting with transaction costs | Active |
| Cloudflare R2 backup | Active |
| Rust order book + execution algos | In progress |
| PyO3 signal bridge (metis-core) | In progress |
| FIX protocol client | In progress |
| RAG indexing pipeline | In progress |
| Tauri desktop UI | In progress |

## Performance Targets

| Metric | Target |
|--------|--------|
| Signal-to-execution latency | < 100ms |
| Order book processing | < 10μs per event |
| Backtest throughput | 1M ticks/second |
| RAG retrieval | < 2s per query |

## Repository Structure

```
metis/                  # Tauri desktop app (React + Rust backend)
metis-core/             # Rust PyO3 library — signal fusion, SIMD, NUMA
execution/              # Rust workspace — order book, execution algos, FIX client
rag/                    # RAG indexing and retrieval pipeline
research/
├── data_ingest/        # API clients for all data sources
├── features/           # Feature engineering
├── models/             # LSTM hybrid model
├── backtest/           # Transaction cost simulator
├── ops/                # Ingestion orchestration scripts
└── tests/              # Test suite
docs/                   # Setup guide and documentation
notes/                  # Research notes and strategy (gitignored)
```

## Getting Started

See [docs/setup.md](docs/setup.md) for full environment setup instructions.

**Quick reference:**
```bash
# Python pipeline
pip install -r research/requirements.txt
python research/ops/ingest_wrapper.py --frequency daily

# Rust execution engine
cd execution && cargo build --release

# Rust core library (PyO3)
cd metis-core && cargo build --release

# Tauri desktop app
cd metis && npm install && npm run tauri:dev
```

Requires Python 3.11+, Rust 1.75+, Node.js 20+. See [docs/setup.md](docs/setup.md) for platform-specific dependency installation.

## License

MIT
