# Metis

Metis is a quantitative research platform for climate-driven energy trading, targeting CME Henry Hub Natural Gas (NG) futures. It combines a Python data and signal pipeline, a Rust low-latency execution engine, and a Tauri desktop interface with LLM-powered signal explanations.

## Architecture

The system is organized into three layers that communicate through well-defined interfaces:

**Research & Signal Generation (Python)**
Data ingestion from 13+ sources feeds a feature engineering pipeline and LSTM hybrid model that produces directional signals on NG futures. Sources include EIA storage reports, FRED macroeconomic series, CME futures via Databento, NOAA/Open-Meteo weather, grid LMP prices across ISO regions, AIS vessel tracking, Congressional climate legislation, and Census building permits. Data is stored locally in SQLite with daily backups to Cloudflare R2.

**Execution Engine (Rust)**
A single-crate workspace (`execution/engine`) hosting a length-prefixed msgpack TCP signal server, a limit order book, TWAP/VWAP execution algorithms, lock-free multi-modal fusion, SIMD batch kernels, and nearest-rank latency reporting with core pinning. The engine responds to a live model signal in ~3.6ms round-trip (target <100ms). A separate C++ HFT engine (`metis-cpp`, maintained in WSL) is under development.

**Interface & Explanation (Tauri + RAG)**
A Tauri 2.0 desktop app drives an Axum orchestrator service (:9000) that runs the Python pipeline over PyO3, queues jobs, persists results to SQLite, and generates LLM signal explanations via a native llama.cpp engine (DeepSeek-R1-Distill-Qwen-7B) grounded by LanceDB vector retrieval — all local CPU, no external API calls.

```
Python predict_and_trade()  →  msgpack/TCP :8080
                            →  order book + TWAP plan
                            →  ExecutionResponse (~3.6ms)
                            →  orchestrator (PyO3)
                            →  SQLite persistence + RAG explanation
                            →  Tauri UI
```

## Status

| Component | Status |
|-----------|--------|
| Python data ingestion (13+ sources) | Active |
| Feature engineering & LSTM model | Active |
| Signal → engine delivery (msgpack/TCP) | Working (3.6ms measured) |
| Rust order book + TWAP/VWAP algos | Active |
| SQLite result persistence | Active |
| RAG indexing + native llama.cpp explanations | Active |
| Cloudflare R2 backup | Active |
| Tauri desktop UI | In progress |
| C++ HFT engine (WSL) | In progress |

## Performance Targets

| Metric | Target |
|--------|--------|
| Signal-to-execution latency | < 100ms |
| Order book processing | < 10μs per event |
| Backtest throughput | 1M ticks/second |
| RAG retrieval | < 2s per query |

## Repository Structure

```
metis/                  # Tauri desktop app (React + Rust backend, Axum orchestrator)
execution/engine/       # Rust execution engine (signal server, order book, TWAP/VWAP)
rag/                    # RAG pipeline: LanceDB + fastembed + native llama.cpp
research/
  data_ingest/          # API clients for all data sources
  features/             # Feature engineering
  models/               # Dual-LSTM inference pipeline
  backtest/             # Transaction cost simulator
  ops/                  # Ingestion orchestration scripts
  tests/                # Test suite
metis-cpp/              # C++ HFT engine — lives in WSL, own repo (not in this checkout)
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

# Rust execution engine (binds 127.0.0.1:8080)
cd execution && cargo build --release --bin metis_server --bin load_test

# Tauri desktop app + orchestrator (:9000)
cd metis && npm install && npm run tauri:dev
```

Requires Python 3.11+, Rust 1.75+, Node.js 20+. Windows builds of `rag` additionally need LLVM/Clang for llama.cpp bindgen. See [docs/setup.md](docs/setup.md) for platform-specific dependency installation.

## License

MIT
