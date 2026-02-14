# METIS ORCHESTRATION ARCHITECTURE
## Option E: Hybrid A+C - Service-Oriented Rust Orchestrator

---

# PROBLEM STATEMENT

Current state:
- Desktop app (Tauri + React) shows MOCK data
- Research pipeline (Python) runs in isolation
- No system-level orchestration
- Optimizations (cache, vectorization, etc.) invisible to app
- User experiences non-functional dashboard

Goal:
- Wire entire system together
- Make optimizations measurable
- Enable real signals to flow to desktop app
- Support daily/on-demand signal generation

**Decision Made:** OPTION E combines low-latency Rust orchestrator (Option A strength) with clean service separation (Option C strength)

---

# ARCHITECTURE OVERVIEW

## How It Works

**User Perspective:**
```
1. User opens Metis desktop app (Tauri)
2. Clicks "Refresh Signals" button
3. React instantly shows loading state
4. App polls background for progress
5. Signals appear as they're generated
6. See performance metrics (3.2s total)
```

**Technical Flow:**
```
React UI
  ↓ invoke('run_pipeline', { mode: 'DEV | REAL' })
Tauri Backend (lib.rs)
  ↓ HTTP POST localhost:9000/api/pipeline/run
  │ { mode, force_refresh: bool }
Orchestration Service
  ├─ Check: Is another pipeline running?
  │  ├─ Yes: Return {status: 'queued'}
  │  └─ No: Continue
  ├─ Step 1: Trigger data ingestion
  │  └─ python research/run_ingestion.py --mode DEV/REAL
  │     ↓ writes to data/metis.db
  ├─ Step 2: Engineer features
  │  └─ python research/models/unify_features.py --db-path data/metis.db
  │     ↓ writes data/features/*.parquet
  ├─ Step 3: Generate signals
  │  └─ python research/models/inference_pipeline.py --features-path data/features
  │     ↓ sends signal to TCP :8080
  ├─ Step 4: Collect responses
  │  └─ Rust service polls TCP :8080
  │     ↓ receives ExecutionResponse
  ├─ Step 5: Save to database
  │  └─ signal_history table INSERT with metrics
  ├─ Return to Tauri
  │  └─ {signals: [...], metrics: {...}, status: 'complete'}
Tauri Backend
  ↓ passes to React
React UI
  ↓ displays real signals
User sees dashboard updates
```

## Directory Structure
```
metis-orchestrator/              (NEW Rust binary)
├── Cargo.toml
├── src/
│   ├── main.rs                  # Entry point, service startup
│   ├── api.rs                   # HTTP routes (/api/pipeline/*)
│   ├── orchestrator.rs          # Core orchestration logic
│   ├── python_runner.rs         # Subprocess management
│   ├── signal_receiver.rs       # TCP :8080 listener
│   ├── db.rs                    # Signal history writes
│   ├── metrics.rs               # Performance tracking
│   ├── job_queue.rs             # Prevent concurrent runs
│   ├── error.rs                 # Error handling
│   └── types.rs                 # Shared types

metis/src-tauri/src/
├── main.rs
└── lib.rs (updated)
    ├── pipeline_bridge.rs       # HTTP client to orchestrator service
    └── invoke_pipeline()        # Tauri command handler

research/
└── orchestrate_daily_pipeline.py (NEW main entry point)
```

## Orchestration Service API

```rust
// HTTP API endpoints

POST /api/pipeline/run
├─ Request:  { mode: "DEV" | "REAL", force_refresh: bool }
├─ Response: { job_id: "abc123", status: "queued|running", phase: "ingestion" }
└─ Returns immediately (async)

GET /api/pipeline/status/:job_id
├─ Response: {
│    job_id: "abc123",
│    status: "running|complete|error",
│    phase: "ingestion|features|inference|signals",
│    progress: 45,                    // percent
│    timing: { ingest: 3.2, feature: 0.8, ... },
│    cache_hits: { lmp: true, cme: true },
│    error: null
│  }
└─ Polling interval: 500ms from React

GET /api/pipeline/results/:job_id
├─ Response: {
│    signals: [
│      { signal_id, timestamp, symbol, direction, confidence, ... },
│      ...
│    ],
│    metrics: {
│      total_time: 4.1,
│      ingest_time: 3.2,
│      feature_time: 0.8,
│      inference_time: 0.1,
│      lmp_cache_hit: true,
│      cme_cache_hit: true,
│      signals_count: 2,
│      avg_confidence: 0.73
│    },
│    execution_responses: [ ... ]
│  }
└─ Called after complete

GET /api/health
├─ Response: { status: "ok", uptime: 3600, version: "0.1.0" }
└─ For monitoring
```

## Error Handling Strategy

```
Scenario 1: Ingestion fails (API error)
  ├─ orchestrator.rs catches error
  ├─ Logs to terminal: [ERROR] LMP fetch failed: gridstatus timeout
  ├─ Returns partial result: {status: 'partial', signals: [cached_old_data]}
  ├─ Tauri shows in React with BANNER:
  │  "⚠️ Unable to fetch latest market data. Showing cached results."
  └─ User can still see historical signals + data

Scenario 2: Feature engineering fails
  ├─ Returns: {status: 'error', error: "Feature vectorization failed"}
  ├─ Tauri shows: "Pipeline failed. Check terminal for details."
  ├─ Terminal shows full stack trace
  └─ User can retry or check logs

Scenario 3: Signal generation fails
  ├─ Model inference error caught
  ├─ Returns last cached signal + error
  ├─ Tauri shows banner + last known signal
  └─ User awareness: "Using previous signal (3h old)"

Scenario 4: Concurrent pipeline trigger
  ├─ Job queue in Rust rejects second request
  ├─ Returns: {status: 'queued', wait_position: 1, eta_seconds: 15}
  ├─ React shows: "Pipeline already running (4s elapsed). Retry in 1min."
  └─ Prevents race conditions
```

## DEV vs REAL Mode

```
DEV MODE (Default, no API calls):
├─ Ingestion: Skips API calls, reads existing data from DB
├─ Features: Uses cached parquet files
├─ Inference: Uses last trained model
├─ Result: Deterministic, repeatable for development
├─ Speed: ~1-2s (pure compute, no network)
└─ Use case: Testing UI, verifying signal format, developing features

REAL MODE (API calls enabled):
├─ Ingestion: Calls gridstatus API for LMP (with 1hr cache)
├─ Ingestion: Calls CME futures API (with 7-day cache)
├─ Ingestion: Calls FRED, EIA, Weather APIs
├─ Features: Processes fresh + cached data
├─ Inference: Uses latest model
├─ Result: Real market signals
├─ Speed: 10-20s (first run includes API calls)
│          3-5s (subsequent runs if cache hits)
└─ Use case: Actual trading, validation

Environment Variable:
  METIS_MODE=DEV  (default)
  METIS_MODE=REAL (requires API keys in .env)
```

---

# DECISIONS MADE

**Architecture:** Hybrid A+C - Service-oriented Rust orchestrator
**Error Handling:** Show stale data + banner (graceful degradation)
**Concurrency:** Queue single job, reject concurrent runs
**Python Environment:** System PATH (already available)
**DEV vs REAL:** Clear distinction - historical data vs API calls
**Signal Flow:** TCP direct collection from executor, write to DB, return to Tauri
**Metrics:** Comprehensive tracking (times, cache hits, signal quality)
**Bundling:** Orchestrator included in Tauri binary (single `npm run tauri dev` starts both)
**Scheduling:** Keep cron/startup script, app handles ad-hoc runs
**Phase 1 Scope:** DEV mode only (fast iteration, no network waits)

---

# RUST CODE QUALITY STANDARDS

**CRITICAL: All Rust code must follow this process before committing:**

```bash
# Step 1: Run Clippy to catch common mistakes and suggest improvements
cargo clippy --all --fix --allow-dirty --allow-staged

# Step 2: Format code according to Rust standards
cargo fmt

# Step 3: Verify no errors remain
cargo clippy --all
cargo build
```

**Why This Matters:**
- `cargo clippy --fix` automatically fixes common issues (unused imports, inefficient patterns)
- `cargo fmt` ensures consistent code style across the entire codebase
- Running these before each commit prevents style drift and bugs
- `--allow-dirty` and `--allow-staged` allow applying fixes to uncommitted changes
- Always run the checks again after to verify nothing broke

**Integration into Workflow:**
1. Write Rust code
2. Run the three commands above
3. Review changes with `git diff`
4. Commit once all checks pass
5. Push to repository

**Before Starting Implementation:**
- [ ] Verify `cargo clippy --version` shows it's installed
- [ ] Verify `cargo fmt --version` shows it's installed
- [ ] Create this as a pre-commit step (optional but recommended)

---

# ACTION ITEMS - IMPLEMENTATION PLANNING

## Prerequisites (Check Before Starting)
- [ ] Rust 1.70+ installed (`rustc --version`)
- [ ] Python in system PATH (`python --version`)
- [ ] Tauri dev environment set up
- [ ] SQLite3 for signal_history table
- [ ] .env file with API keys (for REAL mode)

## Sprint Tasks - Week 1

### PHASE 1A: Create Orchestrator Service (Days 1-2, ~6 hours)

**Goal:** Standalone Rust service that can:
- Spawn Python subprocesses
- Run data ingestion → features → inference
- Collect TCP signals
- Track timing metrics

**Deliverables:**
```
src-tauri/src/orchestrator/
├── main.rs          # Listen on localhost:9000
├── orchestrator.rs  # Pipeline coordination logic
└── types.rs         # Signal, ExecutionResponse, Metrics structs
```

**Testing This Phase:**
```bash
# From metis/ directory
cargo build
cd src-tauri
cargo run --bin orchestrator -- --port 9000

# In another terminal
curl http://localhost:9000/api/health
# Should return: {"status": "ok", "uptime": 5}

# Trigger pipeline
curl -X POST http://localhost:9000/api/pipeline/run -d '{"mode": "DEV"}'
# Should return: {"job_id": "abc123", "status": "running", "phase": "ingestion"}
```

**Rust Code Quality:**
```bash
# After writing code:
cargo clippy --all --fix --allow-dirty --allow-staged
cargo fmt
cargo clippy --all
cargo build
```

### PHASE 1B: HTTP API Layer (Day 2-3, ~3 hours)

**Goal:** Expose orchestrator via HTTP so Tauri/React can call it

**Deliverables:**
```
src-tauri/src/orchestrator/
├── api.rs               # Axum routes
└── main.rs              (updated to start HTTP server)
```

**Endpoints Implemented:**
- `POST /api/pipeline/run` - Start pipeline
- `GET /api/pipeline/status/:job_id` - Get current phase & progress
- `GET /api/pipeline/results/:job_id` - Get final results & metrics
- `GET /api/health` - Health check

**Rust Code Quality:**
```bash
cargo clippy --all --fix --allow-dirty --allow-staged
cargo fmt
```

### PHASE 1C: Tauri Integration (Day 3-4, ~3 hours)

**Goal:** Tauri app calls orchestrator service, displays metrics

**Deliverables:**
```
src-tauri/src/lib.rs    (add Tauri commands)
src/components/
├── PipelineControl.tsx (NEW - button + progress)
├── MetricsPanel.tsx    (NEW - display metrics)
└── SignalsScreen.tsx   (updated - show real signals)
```

### PHASE 1D: Error Handling & Testing (Day 4-5, ~3 hours)

**Goal:** Graceful failures, clear error messages

**Deliverables:**
```
src-tauri/src/orchestrator/
├── error.rs            (NEW - error handling)
└── orchestrator.rs     (updated - error propagation)

research/
└── orchestrate_daily_pipeline.py (NEW - main entry point)
```

### PHASE 1E: Week 1 Validation (Day 5, ~2 hours)

**Terminal Tests:**
- [ ] Service listens on localhost:9000
- [ ] Service spawns Python subprocesses correctly
- [ ] HTTP endpoints respond correctly
- [ ] Error handling shows meaningful messages
- [ ] Job queue rejects concurrent runs

**Tauri/React Tests:**
- [ ] `npm run tauri dev` starts both app and service
- [ ] "Refresh Signals" button triggers pipeline
- [ ] Real signals display (not mocks)
- [ ] Metrics dashboard shows times
- [ ] Error banner shows on failure

**Baseline Metrics Measurement:**
```
Expected for Phase 1:
├─ First run DEV: ~4-5 seconds
├─ Subsequent runs DEV: ~1-2 seconds (if cache hits)
├─ Total speedup vs baseline: 3-15x faster
└─ No mock data, all real signals from DB
```

---

# DELIVERABLES AT END OF WEEK 1

✅ **Working System:**
- Desktop app → Orchestrator service → Python pipeline → Real signals in UI
- Metrics dashboard showing timing and cache effectiveness
- Error handling with graceful degradation
- Baseline measurements captured

✅ **Unblocks Step 3-6:**
- Can now measure if vectorization helps (run before/after)
- Can measure if quantization helps (profiling infrastructure in place)
- Can validate improvements (same signals, just faster)
- Can compare to baseline (15.37s → 4.1s with cache)

✅ **Ready for Week 2:**
- Step 3: Implement vectorization, measure impact
- Step 4: Implement quantization, measure impact
- Step 5: Run backtests
- Step 6: Deploy with monitoring
