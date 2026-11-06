# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Metis is a climate-trading system targeting CME Henry Hub Natural Gas (NG) futures. It combines a Python research/signal pipeline, a C++ primary execution engine (WSL) with a Rust fallback engine, and a Tauri desktop UI with LLM signal explanations.

**Performance**: measured signal→engine round-trip is ~3.6ms Rust / ~0.8–5ms C++ over WSL localhost (target <100ms); RAG chat answers take ~10-12s warm on local CPU (i7-155U, 4 llama.cpp threads).

## Architecture

Three-layer hybrid system:

1. **Python Research Layer** (`research/`) — data ingestion from 13+ APIs (EIA, FRED, CME/Databento, weather, grid LMP, AIS vessels, Congress, Census), feature engineering, Dual-LSTM inference, backtesting with transaction costs.

2. **Execution Engines** — **Primary: C++** (`metis-cpp`, WSL, port 8080). **Fallback: Rust** (`execution/engine`, port 8081) — single-crate workspace (Phase A consolidated the old `metis-core`, `orderbook`, `execution_algos`, `fix_client`, `signal_interface`, `ais_vessel_tracking` crates into it). Both speak the same length-prefixed msgpack TCP protocol (see [docs/cpp-engine-contract.md](docs/cpp-engine-contract.md)); Python fails over automatically and stamps `exec_engine` into signal metadata. Limit order book, TWAP/VWAP algos, nearest-rank latency reporting on both sides; lock-free fusion, SIMD kernels, core pinning on the Rust side. There is no FIX client and no PyO3 extension module anymore.

3. **Frontend Layer** (`metis/src-tauri` + `metis/src`) — Tauri 2.0 desktop app; Axum orchestrator HTTP service on :9000 that drives the Python pipeline over PyO3, queues jobs, persists results to SQLite, and generates RAG explanations through a shared native llama.cpp engine (`rag/src/llm.rs`, no Python LLM detour).

**Core data flow**:
```
research/models/inference_pipeline.py predict_and_trade()
  → SignalClient msgpack/TCP → cpp engine :8080 (primary) → failover rust :8081
  → order book read + TWAP plan → ExecutionResponse (named map)
  → exec_status/exec_latency_ms/exec_engine embedded in signal metadata
  → PyO3 orchestrator parses signals + generates RAG explanations
  → data/orchestrator.sqlite + GET /api/signals/recent → React UI
```

## Commands

### Python (research pipeline)
```bash
pip install -r research/requirements.txt

python research/ops/ingest_wrapper.py --frequency daily   # daily | weekly | monthly | all
python research/ops/ingest_wrapper.py --frequency monthly --only data_ingest.ingest_congress_bills_expanded --force
pwsh research/ops/register_ingestion_task.ps1             # register/repair MetisIngestion task
python research/ops/orchestrate_daily_pipeline.py         # METIS_MODE=DEV|REAL env var selects path
python research/ops/r2_auto_backup.py   # Monday-only weekly-full (Tue-Sun exits; --force-full overrides)
python research/data_ingest/backfill_cme_direct.py
python research/data_ingest/backfill_lmp_prod.py
```
Ingestion runs one child process per ingester with a per-source timeout, so a
hung source is killed without taking the run down. `logs/ingest_ingesters.json`
records each attempt (status, duration, rows, exit code, error) plus source
freshness (`max(date)` vs. the source's publication lag); `--force` re-runs
ingesters the ledger says already succeeded, and a retry with no flags resumes
only what failed. Frequency-level due state is `logs/ingest_ledger.json`.
Source bans, API changes, and reported-vs-actual gaps are tracked in
`docs/data_issues.md`. CME settlements is currently parked there (the host is
IP-blocked for scraping); do not attempt workarounds.

Ingestion is triggered by Scheduled Task `MetisIngestion` (interactive user;
logon +2 min and daily 02:00; `StartWhenAvailable`, `WakeToRun`, `IgnoreNew`,
6h limit). The old Startup-folder `launch_metis.vbs` is renamed `.disabled` —
do not re-enable both. The `Local\MetisIngestion` mutex is the hard
single-instance guard; do not switch the task to "run whether user is logged
on or not" (session 0 breaks the `Local\` mutex and profile caches).
In REAL mode the inference phase loads `models/lstm_ng_predictor.keras`, self-heals missing/stub scalers by refitting from `data/features/train_*.parquet`, reconciles feature columns against `models/lstm_metadata.json`, and sends one signal per run to the engine.

### C++ execution engine (WSL, primary)
```bash
wsl -d Debian -- bash -c "cd /home/tolugenius/Projects/metis-cpp/cpp_engine \
  && cmake --build build --target metis-tests metis-server"
ctest --test-dir build             # 34 gtests incl. wire-format fixtures
./build/src/bin/metis-server       # binds 127.0.0.1:8080, logs to stdout
```
See [docs/cpp-engine-contract.md](docs/cpp-engine-contract.md) for the wire protocol and the long-running-server launch pattern.

### Rust fallback engine (`execution/`)
```bash
cargo build --release --bin metis_server --bin load_test   # fat LTO: ~1min even for one-line changes
cargo test -p engine
cargo bench -p engine        # simd_vectorization, realistic_simd, lockfree_fusion, bridge_latency, lob_performance
./target/release/metis_server.exe   # binds 127.0.0.1:8081 (secondary), logs to stdout
./target/release/load_test.exe      # defaults to 127.0.0.1:8081
```
When launching `metis_server` from agent tooling, redirect stdout AND stderr to files and stop it within the same command — it is a long-lived listener, and anything waiting on its process tree will appear hung.

### Tauri app / orchestrator (`metis/`)
```bash
npm install
npm run dev              # frontend only (Vite)
npm run tauri:dev        # full Tauri dev mode
npm run tauri:build      # production build
npm run build            # TypeScript + Vite build
npm run test:service     # orchestrator integration tests
cargo test --lib         # in metis/src-tauri/
```
Orchestrator HTTP API (:9000): `POST /api/pipeline/run {mode}`, `GET /api/pipeline/status/:job_id`, `GET /api/pipeline/results/:job_id`, `GET /api/signals/recent?limit=`. Standalone binary: `cargo run --release --bin orchestrator`.

### RAG (`rag/`)
```bash
cargo test -p rag
cargo run --release -p rag --example llm_smoke
```
LLM sidecar: vendored upstream `llama-server` (b11669, `rag/llm/server/`, git-ignored) on 127.0.0.1:8082 serving `rag/llm/DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf`; `rag/src/llm.rs` is a thin HTTP client + supervisor (spawns on demand, kills on drop, reuses if already up). Deterministic preset: temp 0.0, fixed seed 42, server-side stops. `METIS_LLM_THREADS` (default 6 — measured knee on i7-155U; 1 = byte-identical, ~1/4 speed), `METIS_LLM_TEMP`/`METIS_LLM_SEED` (`random` opts out), `METIS_LLM_URL` (external server, never supervised).

## Key Files

| File | Purpose |
|------|---------|
| `execution/engine/src/signal_interface.rs` | Rust fallback TCP signal server/client; responses must stay `rmp_serde::to_vec_named` (named maps) |
| `execution/engine/src/bin/metis_server.rs` | Wires SignalServer → book + TWAP; secondary engine on 8081 |
| `metis-cpp` (WSL) `src/bin/metis_server.cpp` | Primary engine: msgpack/TCP server on 8080; see [docs/cpp-engine-contract.md](docs/cpp-engine-contract.md) |
| `execution/engine/src/{fusion,simd,latency}.rs` | Lock-free fusion, SIMD batch processing, nearest-rank percentiles |
| `metis/src-tauri/src/bin/orchestrator.rs` | Standalone orchestrator binary + Axum server |
| `metis/src-tauri/src/orchestrator/server.rs` | Routes, job queue wiring, queued-job promotion |
| `metis/src-tauri/src/orchestrator/persistence.rs` | SQLite jobs/signals tables under `data/orchestrator.sqlite` |
| `metis/src-tauri/src/orchestrator/python_runner.rs` | PyO3 driver — imports `research.ops.orchestrate_daily_pipeline` |
| `research/models/inference_pipeline.py` | Dual-LSTM inference, scaler self-heal, schema reconciliation, signal send |
| `research/models/config/model_config.yaml` | Model config; feature lists may drift from `models/lstm_metadata.json` (metadata wins) |
| `research/ops/orchestrate_daily_pipeline.py` | Ingestion → features → inference orchestration (DEV synthetic vs REAL model) |
| `research/signal_client.py` | msgpack/TCP client used by inference (port 8080) |
| `rag/src/llm.rs` | Sidecar HTTP client + supervisor (owns the llama-server child, kills on drop; replaces the removed in-process bindings) |
| `.env` | API keys; `METIS_MODE=PROD` is also read by some research paths |

## Cargo Workspace Layout

- `execution/` — workspace with a single member, `engine` (all former member crates were merged into it during Phase A consolidation).
- `metis/src-tauri/` — standalone crate (Tauri's build tooling requires it); depends on `rag` via path.
- `rag/` — standalone crate: LanceDB store, fastembed embeddings, native llama.cpp LLM.

## C++ Engine (lives in WSL)

The C++ HFT engine (`metis-cpp`) is maintained exclusively in WSL at `/home/tolugenius/Projects/metis-cpp` (Windows path: `\\wsl.localhost\Debian\home\tolugenius\Projects\metis-cpp`). It is its own git repo and builds natively in WSL with CMake. It is the **primary live trading engine** (port 8080); the Rust engine is the fallback (8081). There is deliberately **no copy of it inside this Windows checkout** — do not recreate one; edit/build it from WSL. Wire protocol and engine semantics: [docs/cpp-engine-contract.md](docs/cpp-engine-contract.md).

## Release Profile (Rust)

All Rust crates use aggressive release settings: `opt-level=3`, `lto="fat"`, `codegen-units=1`, `panic="abort"`, `strip=true`. Benchmark with `cargo bench`, not debug builds. First release builds of `rag` are slow (lancedb/ort graphs; the old llama.cpp ~400-TU cmake compile is gone since the sidecar switch); iterate with `cargo check --lib` / `cargo test --lib` instead.

## Environment Setup

Full setup instructions in [docs/setup.md](docs/setup.md). Requires: Rust 1.75+, Python 3.11+, Node.js 20+, MSVC 2022 (Windows), LLVM/Clang for `rag` (llama.cpp bindgen).

Copy `.env.example` → `.env` and populate API keys before running ingestion pipelines.

**Windows quirk**: the repo-root `.cargo/config.toml` force-sets `LIBCLANG_PATH` to `C:\Users\legot\scoop\apps\llvm\current\bin` because a stale machine-level `LIBCLANG_PATH` points at a removed LLVM install and silently overrides plain config values (`force = true` is required).

## Data Storage

- **SQLite** — primary local store for time-series data; orchestrator results live in `data/orchestrator.sqlite`
- **LanceDB** — vector DB for RAG embeddings; canonical corpus at `data/lance/` (the old `research/data/dev/lance` was removed)
- **Cloudflare R2** — Monday-only weekly-full backup of ingested data (`research/ops/r2_auto_backup.py`)
- **`research/data/`** — cached datasets and metadata JSONs (frequently-dirty metadata files are intentionally left uncommitted)
- **`data/features/`** — train/test parquet splits matching the trained model schema (14 daily + 36 low-freq + 4 sparse features)
- **`stooq_hist_data/`** — kept intentionally, may be needed later
