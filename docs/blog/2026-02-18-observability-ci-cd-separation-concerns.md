---
layout: post
title: "Observability & CI/CD: Separation of Concerns"
date: 2026-02-18
author: Researcher
categories: [Infrastructure, Observability, DevOps]
---

# Observability & CI/CD: Separation of Concerns

There's a pattern in how systems degrade: they start with one job, then accumulate others until clarity breaks down.

GitHub Actions started as a gatekeeper: "Can this code be safely merged?" It's good at that job. But there's pressure to add other questions: "Is the system healthy? Can we reach the database? Did the data source publish today?"

Those are different jobs. Different concerns. Different timelines. Mixing them breaks both.

This post explores how we're separating these concerns in Metis, where we've already succeeded with tiered CI/CD workflows, and where in-app observability still needs work.

---

## The Separation Principle

**GitHub Actions should answer:** "Is this PR safe to merge?"

✅ Syntax validation (pylint, clippy)  
✅ Type checking (mypy, cargo)  
✅ Unit tests (pytest, cargo test)  
✅ Build verification (npm, cargo)  
✅ Artifact creation (wheels, binaries)  

These are **deterministic, fast, and self-contained**. They require no external services, no runtime context.

**In-app observability should answer:** "Is the system operational?"

✅ Data freshness monitoring (EIA published today? Congress.gov reachable?)  
✅ API health checks (Milvus accepting requests? LLM model loaded?)  
✅ Integration tests (end-to-end signal generation works?)  
✅ Production metrics (signal latency p95? Cache hit rate?)  
✅ Calibration tracking (past explanations accurate? Confidence well-calibrated?)  

These require **runtime context, actual data, and operational visibility**. They can't be gatekeepers; they're dashboards.

The tension: both feel like they belong in CI/CD. But mixing them creates false gates ("PR fails because Congress.gov is down—is that the developer's fault?") and lost observability (workflow runs once per PR, but the system runs 24/7).

---

## Current State: Tiered CI/CD

We've already started separating concerns with a tiered workflow structure:

**Tier 0 (CI baseline):** Lint, type check, import validation  
**Tier 1 (Integration validation):** Build verification, unit tests  
**Tier 2 (Chaos testing):** Stress tests, edge cases  

Each tier is self-contained. Tier 0 gates PRs; Tier 1 informs but doesn't block; Tier 2 is informational for risk assessment.

Here's the current [tier-0-ci.yml](../.github/workflows/tier-0-ci.yml) structure:

```yaml
name: Tier 0 - CI/CD Baseline (Lint + Type Check + Imports)
on: [push, pull_request]

jobs:
  python-lint:
    - Lint with pylint (non-blocking)
    - Check format with black
    - Check import sorting
  
  python-typecheck:
    - Type check with mypy
  
  python-imports:
    - Validate core imports can load
    - Check for circular imports
  
  rust-check:
    - Cargo check
    - Clippy linting (non-blocking)
```

**What's good here:** Clear tiers, explicit priorities (some checks block, others don't), parallel execution.

**What's missing:** In-app observability infrastructure to *use* the health information that tight integration would give us.

---

## Problem 1: Non-Blocking Checks Hide Regressions

Look at the tier-0 workflow summary:

```yaml
summary:
  name: CI Summary
  runs-on: ubuntu-latest
  needs: [python-lint, python-typecheck, python-imports, rust-check]
  if: always()
  steps:
    - name: Check workflow status
      run: |
        if [ "${{ job.status }}" == "failure" ]; then
          echo "⚠ CI checks completed with warnings (non-blocking)"
          exit 0
        else
          echo "✅ All CI checks passed"
        fi
```

Several checks use `continue-on-error: true`:

```yaml
- name: Lint with pylint (non-blocking)
  run: pylint research/ --exit-zero ...
  continue-on-error: true

- name: Check code format with black
  run: black --check research/ || true
  continue-on-error: true

- name: Clippy linting (non-blocking)
  run: cargo clippy --all-targets -- -D warnings || true
  continue-on-error: true
```

**Why it matters:**

These checks fail silently. A developer sees "✅ CI passed" even though pylint found 47 errors or clippy found warnings. The signal degrades gradually:
- Week 1: 5 warnings get ignored
- Week 2: 15 warnings
- Week 3: Code is unmaintainable

But the CI always reports "passed."

**This is intentional**—we don't want to block merges on style issues. But the cost is buried visibility.

**Phase 1 fix:**

Separate **blocking** from **informational**:

```yaml
jobs:
  # BLOCKING: Must pass to merge
  strict-checks:
    runs-on: ubuntu-latest
    steps:
      - name: Type check with mypy
        run: mypy research/metrics.py --ignore-missing-imports
        # No continue-on-error: fails the PR

      - name: Validate imports
        run: python -c "from research.metrics import MetricsCollector"
        # Fails on import errors

  # INFORMATIONAL: Logged, not blocking
  linting-quality:
    runs-on: ubuntu-latest
    continue-on-error: true
    steps:
      - name: Pylint (code quality)
        run: pylint research/ --disable=all --enable=syntax-error,import-error

      - name: Format check (black)
        run: black --check research/ || true

      - name: Clippy (Rust warnings)
        run: cargo clippy --all-targets -- -D warnings || true

  summary:
    needs: [strict-checks, linting-quality]
    if: always()
    steps:
      - name: Report results
        run: |
          if [ "${{ needs.strict-checks.result }}" == "failure" ]; then
            echo "❌ Blocking checks failed—cannot merge"
            exit 1
          else
            if [ "${{ needs.linting-quality.result }}" == "failure" ]; then
              echo "⚠ Merge approved, but linting issues detected (see artifacts)"
            else
              echo "✅ All checks passed"
            fi
          fi
```

**Success metric:** A diff shows which checks are blocking vs. informational, visual feedback on which ones matter for merging.

---

## Problem 2: Output Suppression Loses Visibility

In [orchestrate_daily_pipeline.py](research/orchestrate_daily_pipeline.py), we see this pattern:

```python
def run_features_phase(mode: str, logger) -> tuple[bool, float, list]:
    """Run feature engineering phase"""
    logger.info(f"[FEATURES] Starting feature engineering phase (mode: {mode})")
    
    try:
        from research.models.unify_features import main as features_main
        import io
        from contextlib import redirect_stdout, redirect_stderr
        
        # Capture and discard output
        f_out = io.StringIO()
        f_err = io.StringIO()
        with redirect_stdout(f_out), redirect_stderr(f_err):
            features_main()
        
        elapsed = time.time() - start
        logger.info(f"[FEATURES] Phase completed in {elapsed:.2f}s")
        return True, elapsed, errors
    except Exception as e:
        logger.error(f"[FEATURES] {error_msg}")
```

This suppresses all output from `features_main()`. If it runs 50 steps and 3 fail, we log the exception but lose detail about which steps succeeded.

**Why it matters:**

When a phase fails, we need to know *why*. Was it a data loading issue? A computation error? A timeout? Without structured output from each step, debugging requires re-running the pipeline locally.

**Phase 1 fix:**

Instead of suppressing output, use structured logging:

```python
def run_features_phase(mode: str, logger) -> tuple[bool, float, list]:
    """Run feature engineering phase"""
    logger.info(f"[FEATURES] Starting feature engineering phase (mode: {mode})")
    start = time.time()
    
    try:
        from research.models.unify_features import main as features_main
        
        # Call with logger, not suppressed
        feature_count = features_main(logger=logger)
        
        elapsed = time.time() - start
        logger.info(
            f"[FEATURES] Phase completed successfully",
            extra={
                "duration_seconds": elapsed,
                "features_created": feature_count
            }
        )
        return True, elapsed, []
    
    except Exception as e:
        elapsed = time.time() - start
        error_msg = f"Features phase failed: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False, elapsed, [error_msg]
```

Then `features_main()` logs each step:

```python
def main(logger=None):
    """Build feature matrix from raw data"""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("[FEATURES] Loading raw data")
    data = load_data()
    logger.info(f"[FEATURES] Loaded {len(data)} rows")
    
    logger.info("[FEATURES] Computing technical indicators")
    indicators = compute_indicators(data)
    logger.info(f"[FEATURES] Computed {len(indicators)} indicators")
    
    logger.info("[FEATURES] Creating feature matrix")
    features = create_matrix(data, indicators)
    logger.info(f"[FEATURES] Created matrix: shape {features.shape}")
    
    return len(features)
```

Now the log shows exactly which step failed and at what point.

**Success metric:** When a phase fails, logs show all completed steps and the exact failure point without re-running.

---

## Problem 3: No Per-Ingester Visibility

In [run_all_ingesters.py](research/data_ingest/run_all_ingesters.py), the code returns overall success/failure:

```python
def run_all(frequency: str = "all", collector=None) -> Tuple[bool, List[Dict]]:
    """Run ingesters. Returns (overall_success, results)"""
    ingesters = get_ingesters_for_frequency(frequency)
    results = []
    all_ok = True
    
    for name, module in ingesters:
        start_time = time.time()
        status = "success"
        error_msg = None
        row_count = 0
        
        try:
            print(f"\n--- Running {name} ingester ---")
            if hasattr(module, 'main'):
                result = module.main()
                if isinstance(result, int):
                    row_count = result
            else:
                status = "failed"
                error_msg = "No main() function"
                all_ok = False
        
        except Exception as e:
            status = "failed"
            error_msg = str(e)
            all_ok = False
```

Results are collected but what happens next? Let's see further down...

Looking at this, the structure is already capturing per-ingester data. Good! But is it being *used* by the orchestrator?

**Why it matters:**

The orchestrator should not treat "1 ingester failed" the same as "11 ingesters failed." EIA failed—critical, lower confidence. Congress.gov failed—important but not critical. Weather data not available—low impact.

Right now, the orchestrator gets `(success: bool, elapsed: float)` and logs broad failures. But doesn't adjust signal confidence based on *which* data sources are unavailable.

This ties back to the ContextSnapshot from Part 1: when explaining a signal, we should know whether EIA data is fresh, stale, or missing, and adjust confidence accordingly.

**Phase 1 fix:**

Ensure ingester results are structured and returned to orchestrator:

```python
@dataclass
class IngestionResult:
    ingester_name: str
    status: str  # "success", "failure", "timeout"
    duration: float
    rows_inserted: int
    data_as_of: Optional[datetime]
    error: Optional[str] = None

def run_all(frequency: str = "all", collector=None) -> Tuple[bool, List[IngestionResult]]:
    """Run ingesters. Returns (overall_success, detailed_results)"""
    ingesters = get_ingesters_for_frequency(frequency)
    results = []
    all_ok = True
    
    for name, module in ingesters:
        start_time = time.time()
        
        try:
            logger.info(f"[INGEST] Running {name}")
            rows = module.main()
            
            result = IngestionResult(
                ingester_name=name,
                status="success",
                duration=time.time() - start_time,
                rows_inserted=rows,
                data_as_of=datetime.utcnow()
            )
            results.append(result)
            logger.info(
                f"[INGEST] {name} succeeded",
                extra={
                    "rows_inserted": rows,
                    "duration_seconds": result.duration
                }
            )
        
        except Exception as e:
            result = IngestionResult(
                ingester_name=name,
                status="failure",
                duration=time.time() - start_time,
                rows_inserted=0,
                error=str(e)
            )
            results.append(result)
            all_ok = False
            logger.error(
                f"[INGEST] {name} failed",
                extra={"error": str(e)}
            )
    
    return all_ok, results
```

Then in the orchestrator:

```python
def run_ingest_phase(mode: str, logger, collector=None) -> tuple[bool, float, list]:
    """Run data ingestion phase"""
    logger.info(f"[INGEST] Starting ingestion phase (mode: {mode})")
    start = time.time()
    
    ingest_ok, ingester_results = ingest_run_all(frequency="all", collector=collector)
    
    elapsed = time.time() - start
    
    # Log per-ingester results
    for result in ingester_results:
        if result.status == "success":
            logger.info(
                f"[INGEST] {result.ingester_name}: {result.rows_inserted} rows in {result.duration:.2f}s"
            )
        else:
            logger.warning(
                f"[INGEST] {result.ingester_name}: FAILED ({result.error})"
            )
    
    # Summary
    passed = sum(1 for r in ingester_results if r.status == "success")
    failed = sum(1 for r in ingester_results if r.status == "failure")
    
    logger.info(
        f"[INGEST] Phase completed: {passed} passed, {failed} failed in {elapsed:.2f}s"
    )
    
    # Store results for dashboard
    if collector:
        collector.record_ingest_phase(ingester_results)
    
    return ingest_ok, elapsed, []
```

Now the dashboard (Phase 2) can show:
- ✅ EIA: 5,000 rows, 2.3s
- ✅ LMP: 15,000 rows, 1.8s
- ❌ Congress: timeout after 30s

Instead of just "Ingest: OK" or "Ingest: FAILED".

**Success metric:** Dashboard shows per-ingester status and timing; failed sources are visible and can inform signal confidence.

---

## Problem 4: Cross-System Tracing Requires Correlation IDs

Consider this request path:
1. Frontend calls `explain_trading_signal`
2. Tauri backend logs: "Processing signal X123"
3. Calls Python retrieval pipeline
4. Calls RAG engine
5. Error occurs (but which component?)

Without correlation IDs, logs look like:

```
[2026-02-18 10:23:45] explain_trading_signal started
[2026-02-18 10:23:45] Retrieving documents
[2026-02-18 10:23:46] ERROR: LanceDB connection refused
```

How do we know these logs belong together? We don't. Debugging requires grepping by timestamp and praying they're close enough.

**Phase 1 fix:**

Pass a correlation ID from frontend through every layer:

```typescript
// Frontend (SignalExplainer.tsx)
const correlationId = `explain_${uuidv4()}`;
const response = await invoke('explain_trading_signal', {
    signal,
    correlation_id: correlationId
});
```

```rust
// Tauri backend (lib.rs)
#[tauri::command]
async fn explain_trading_signal(
    signal: serde_json::Value,
    correlation_id: String,
) -> Result<ExplanationResponse, String> {
    tracing::debug!("explain_trading_signal started", correlation_id = &correlation_id);
    
    let rag = get_rag_engine()?;
    let result = rag.explain(signal, &correlation_id).await?;
    
    tracing::debug!("explain_trading_signal completed", correlation_id = &correlation_id);
    Ok(result)
}
```

```python
# retrieval_pipeline.py
def retrieve(self, query: str, correlation_id: str = None) -> List[Document]:
    logger.debug(
        "Retrieving documents",
        extra={"correlation_id": correlation_id}
    )
    
    embeddings = self.embedding_model.encode(query)
    results = self.lance.search(embeddings)
    
    logger.debug(
        f"Retrieved {len(results)} documents",
        extra={"correlation_id": correlation_id}
    )
    return results
```

Update log format to include correlation_id:

```python
logger.add(
    str(log_file),
    format="{time:YYYY-MM-DD HH:mm:ss} | {extra[correlation_id]:>12} | {level: <8} | {message}",
    level="INFO"
)
```

Now logs are grouped by request:

```
[2026-02-18 10:23:45] explain_abc123 | explain_trading_signal started
[2026-02-18 10:23:45] explain_abc123 | Retrieving documents
[2026-02-18 10:23:46] explain_abc123 | ERROR: LanceDB connection refused
```

A single grep finds all logs for that request.

**Success metric:** All logs from a single user request have the same correlation ID; tracing a failure takes one grep query.

---

## Problem 5: Session Metrics Not Persisted

The `SessionManager` in [rag_engine.rs](../../execution/src/rag_engine.rs) tracks token usage in-memory:

```rust
pub struct SessionManager {
    pub session_id: String,
    pub tokens_used: usize,
    pub message_count: usize,
}
```

When the app closes, this data is lost. We can't answer:
- How many tokens did User A use today?
- What's the token budget trend over the past week?
- Are we approaching the monthly limit?

**Phase 1 fix:**

Persist token events to a database:

```python
# rag/token_tracker.py
@dataclass
class TokenEvent:
    timestamp: datetime
    session_id: str
    message_number: int
    role: str  # "user" or "assistant"
    token_count: int
    cumulative_tokens: int
    event_type: str  # "message_added", "session_created", "session_closed"

class TokenEventLog:
    def __init__(self, db_path: str):
        self.db = sqlite3.connect(db_path)
        self._init_table()
    
    def _init_table(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS token_events (
                id INTEGER PRIMARY KEY,
                timestamp DATETIME,
                session_id TEXT,
                message_number INTEGER,
                role TEXT,
                token_count INTEGER,
                cumulative_tokens INTEGER,
                event_type TEXT
            )
        """)
        self.db.commit()
    
    def record(self, event: TokenEvent):
        self.db.execute(
            """INSERT INTO token_events VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)""",
            (event.timestamp, event.session_id, event.message_number,
             event.role, event.token_count, event.cumulative_tokens, event.event_type)
        )
        self.db.commit()
```

Tell Tauri backend to log token events:

```rust
#[tauri::command]
async fn record_token_event(
    session_id: String,
    message_number: usize,
    token_count: usize,
) -> Result<(), String> {
    // Call Python function to persist
    python_bridge::record_token_event(session_id, message_number, token_count)
        .map_err(|e| e.to_string())
}
```

Now token usage is queryable and visible in dashboards.

**Success metric:** "Session token usage" dashboard shows daily/weekly/monthly trends; alerts when approaching monthly limit.

---

## The In-App Observability Dashboard (Phase 2)

Once structured logging and persistence are in place, we build a single dashboard for system health. This is **not** CI/CD; it's operations visibility.

**AdminScreen** (new settings tab):

- **Pipeline Status**: Last ingest run (when, which sources passed/failed, timing)
- **Data Freshness**: EIA (updated 2h ago), Congress (5d ago—stale), Weather (1h ago)—with confidence adjustments
- **RAG Status**: Document count per source, retrieval latency p50/p95/p99
- **Session Analytics**: Active sessions, token usage per session, handoff count
- **Calibration**: Predictions from 7 days ago vs. actual outcomes
- **Error Log**: Last 100 errors, grouped by correlation ID, searchable

All of this data is collected by in-app components (`DataSourceMonitor`, `MetricsCollector`, `TokenEventLog`, etc.) and exposed via Tauri commands to the frontend.

---

## Phase 1 Checklist

**CI/CD Clarity:**
- [ ] Split CI jobs into blocking (type check, imports) vs. informational (linting, style)
- [ ] Make workflow summary clear about which checks are required for merge
- [ ] Document decision: non-blocking checks inform developers but don't block PRs

**Logging Improvements:**
- [ ] Remove output suppression (`redirect_stdout`) from high-level orchestration
- [ ] Update phase runners (features, inference) to log sub-steps instead of just success/failure
- [ ] Add timing breakdown: how long per sub-step?

**Per-Component Visibility:**
- [ ] Define `IngestionResult` dataclass (ingester_name, status, rows, duration, data_as_of)
- [ ] Update `run_all_ingesters()` to return structured results per ingester
- [ ] Update orchestrator to log per-ingester results, not bulk success/failure
- [ ] Add ingester status summary to orchestration logs

**Correlation IDs:**
- [ ] Add correlation_id parameter to `explain_trading_signal` Tauri command
- [ ] Pass correlation_id through rag_engine and retrieval_pipeline
- [ ] Update log format to include correlation_id in all logs
- [ ] Document correlation ID pattern for future commands

**Token Tracking (setup only):**
- [ ] Create `TokenEventLog` class with SQLite schema
- [ ] Add Tauri command `record_token_event()`
- [ ] Verify schema and queries work with test data

---

## Phase 1 Success Metrics

**CI Visibility:**
- Developers can quickly identify whether a CI failure blocks merge or is just informational
- Lint/format issues logged to dashboard, not to PR status

**Logging Completeness:**
- When a phase fails, logs show exactly which sub-step failed and required context
- No need to re-run pipeline locally to debug (unless it's a rare edge case)

**Per-Component Transparency:**
- Ingestion summary shows which of N data sources succeeded/failed
- Orchestrator logs match ingester count (if N ingesters, N log lines for results)

**Cross-System Tracing:**
- Grep a single correlation ID finds all logs for one user request across all components
- Error messages include correlation ID so support can trace requests

**Foundation for Phase 2:**
- TokenEventLog persists events; queries work
- AdminScreen infrastructure ready (commands defined, data structure clear)

---

## What's Next

Next post: UX Design — From monolith to responsive, accessible, persistent.