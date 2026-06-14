# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Metis is a production HFT-enhanced climate trading system targeting CME Henry Hub Natural Gas (NG) futures. It combines Python ML/data pipelines, a Rust low-latency execution engine, and a Tauri desktop UI.

**Performance targets**: signal-to-execution <100ms, order book processing <10μs/event, backtest throughput 1M ticks/sec, RAG retrieval <2s.

## Architecture

Three-layer hybrid system:

1. **Python Research Layer** (`research/`) — data ingestion from 15+ APIs (EIA, FRED, CME/Databento, weather, grid LMP, AIS vessels, Congress, Census, etc.), LSTM hybrid ML models, policy sentiment via RAG, backtesting with transaction costs.

2. **Rust Execution Layer** (`metis-core/`, `execution/`) — lock-free multi-modal signal fusion (`crossbeam::SegQueue` + atomics), SIMD batch processing, NUMA thread pinning (Windows `winapi`), limit order book simulator, TWAP/VWAP algos, FIX protocol over WebSocket.

3. **Frontend Layer** (`metis/`) — Tauri 2.0 desktop app (React + Rust backend), Axum HTTP server for IPC, real-time LLM explanation chat (RAG), Recharts + lightweight-charts dashboards.

**Core data flow**:
```
Python ML signals → PyO3 bridge (metis-core/src/bridge.rs)
                 → Rust engine fusion (fusion.rs)
                 → Order book + execution algos
                 → FIX protocol → market
                 → RAG explanation pipeline → React UI
```

## Commands

### Python (research pipeline)
```bash
pip install -r requirements.txt

# Data ingestion
python research/ops/ingest_wrapper.py --frequency daily   # daily | weekly | monthly | all
python research/orchestrate_daily_pipeline.py

# Individual runners
python research/run_ingestion.py
python research/metrics_service.py
python research/r2_auto_backup.py
python research/backfill_cme_direct.py
python research/backfill_lmp_prod.py
```

### Rust execution engine (`execution/` workspace)
```bash
cargo build --release
cargo test
cargo bench
```

### Rust core library (`metis-core/` — PyO3 extension)
```bash
cargo build --release   # produces libmetis_core.so / .pyd
cargo bench             # simd_vectorization, lockfree_fusion, bridge_latency, realistic_simd
```

### Tauri desktop app (`metis/`)
```bash
npm install
npm run dev              # frontend only (Vite)
npm run tauri:dev        # full Tauri dev mode
npm run tauri:build      # production build
npm run build            # TypeScript + Vite build
npm run test:service     # orchestrator integration tests
```

## Key Files

| File | Purpose |
|------|---------|
| `metis-core/src/bridge.rs` | PyO3 interface — Python signals → Rust engine |
| `metis-core/src/fusion.rs` | Lock-free multi-modal signal aggregation |
| `metis-core/src/simd.rs` | SIMD vectorized alternative data processing |
| `metis-core/src/numa.rs` | Windows thread-core pinning |
| `metis/src-tauri/src/bin/orchestrator.rs` | Main Tauri binary + Axum server |
| `metis/src/App.tsx` | React root |
| `research/orchestrate_daily_pipeline.py` | Full data + signal generation pipeline |
| `research/signal_client.py` | Sends signals to Rust via PyO3 |
| `research/ops/ingest_wrapper.py` | Top-level ingestion orchestrator |
| `rag/retrieval_pipeline.py` | Semantic search + LLM orchestration |
| `.env` | All API keys (OpenAQ, FRED, EIA, Finnhub, Ember, CME, etc.) |

## Cargo Workspace Layout

`execution/` is a Cargo workspace containing:
- `orderbook/` — limit order book + PCAP parser
- `execution_algos/` — TWAP/VWAP implementations
- `fix_client/` — FIX protocol session handler (tokio-tungstenite)
- `signal_interface/` — Python→Rust IPC bridge
- `ais_vessel_tracking/` — alternative data collection

`metis-core/` is a separate crate (not part of `execution/` workspace).

## Release Profile (Rust)

All Rust crates use aggressive release settings: `opt-level=3`, `lto="fat"`, `codegen-units=1`, `panic="abort"`, `strip=true`. Benchmark with `cargo bench` against criterion suite, not debug builds.

## Environment Setup

Full setup instructions in [docs/setup.md](docs/setup.md). Requires: Rust 1.75+, Python 3.11+, Node.js 20+, CMake 3.20+, MSVC 2022 (Windows), OpenSSL 3.0+.

Copy `.env.example` → `.env` and populate API keys before running ingestion pipelines.

## Data Storage

- **SQLite** — primary local store for time-series data
- **LanceDB** — vector DB for RAG embeddings (default, no Docker required)
- **CloudFlare R2** — daily backup of ingested data (`research/r2_auto_backup.py`)
- **`research/data/`** — local cached datasets and metadata JSONs
