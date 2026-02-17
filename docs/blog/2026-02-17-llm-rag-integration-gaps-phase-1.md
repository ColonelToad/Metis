---
layout: post
title: "LLM + RAG Part 2: Integration Gaps & Phase 1 Implementation"
date: 2026-02-17
author: Researcher
categories: [Engineering, LLM, RAG]
---

# LLM + RAG Part 2: Integration Gaps & Phase 1 Implementation

In [Part 1](2026-02-16-llm-rag-groundwork-and-future-ux.md), we laid out the 8-step framework for explainable trading signal generation: reference class lookup, ensemble aggregation, Bayesian updates, scenario generation, expected value calculation, risk assessment, explanation generation, and calibration tracking.

The framework exists—on paper. The code? That's where things get interesting.

## The Gap Between Design and Code

There's a common pattern in systems built incrementally: the architecture evolves faster than the implementation. You document the ideal state (8 steps, structured outputs, persistent snapshots), but the actual code does 4 steps, returns free-form text, and loses state when the app closes.

This post explores five concrete gaps in our current RAG implementation and proposes Phase 1 fixes—minimal, measurable changes that close the gap without redesigning everything.

## Problem 1: RAG Initialization Is Silent

When the Metis app starts, the RAG engine claims "ready" within milliseconds. But indexing documents happens in the background. A user clicking "Explain" 5 seconds after startup gets an explanation with zero context.

**What's happening:**

The [`init_rag_engine`](rag_engine.rs#L20-L50) function in our Rust backend:
1. Spawns document indexing as a background task
2. Immediately returns `RAG_STATUS = "Ready"`
3. Actually indexing happens asynchronously and completes 5–10 seconds later

If a user requests an explanation before indexing finishes, the signal gets explained without any retrieved documents—fallback template only.

**Why it matters:**

Users have no visibility into this race condition. They see a response and assume the context was factored in. They don't know the difference between "explanation with documents" and "explanation without documents" because both look the same: a plausible-sounding narrative.

**Phase 1 fix:**

Instead of fire-and-forget, poll the indexing task:

```
RAG_STATUS = "Initializing"
↓
[Spawn document indexing task]
↓
[Wait for first document successfully indexed]
↓
RAG_STATUS = "Ready"
```

Keep `RAG_STATUS = 1` (Initializing) until the DocumentStore is created *and* at least one document is indexed. Only then set `RAG_STATUS = 2` (Ready).

Add a timeout: if indexing doesn't complete in 30 seconds, use a degraded mode with cached fallbacks rather than blocking forever.

**Success metric:** The initial `explain_trading_signal` request always receives context, measured by checking that the response includes retrieved document metadata.

---

## Problem 2: 4-Step Output Instead of 8-Step

The ExplanationData struct in our code captures:

```
- market_analysis (Step 7: Generation)
- signal_drivers (partial Step 7)
- risks (Step 6: Risk Assessment)
- expected_outcome (Step 5: Expected Value)
```

What's missing:

```
- Step 1: Reference Class Lookup (base rate of similar trades)
- Step 2: Ensemble Aggregation (which models voted, how were they weighted)
- Step 3: Bayesian Update (prior vs posterior confidence)
- Step 4: Scenario Generation (what happens if X changes)
- Step 8: Calibration (how accurate were past explanations)
```

**Why it matters:**

Without these, we can't:
- Debug signal quality independently of explanation quality
- Inspect ensemble voting (was it 10 models agreeing or 1 strong model drowning out 9 weak ones?)
- Understand tail scenarios (what does the model think goes catastrophically wrong?)
- Track calibration over time (are our confidence estimates accurate?)

The 8-step framework is *documented* but not *observable* in the API response.

**Phase 1 fix:**

Expand the ExplanationData struct to include all 8 steps as explicit fields with structured data:

```
ReferenceClassData: {
  reference_class_name,
  historical_base_rate,
  similar_trades_count,
  average_outcome
}

EnsembleData: {
  model_weights (HashMap),
  aggregation_method,
  disagreement_score
}

BayesianData: {
  prior_confidence,
  posterior_confidence,
  evidence_strength
}

ScenarioData: {
  scenario_name,
  probability,
  outcome_if_true,
  tail_risk_indicator
}
```

Each step becomes queryable and loggable independently of the LLM explanation text.

**Success metric:** Explanation response includes at least 7 of 8 steps with non-null data (Step 8—calibration—is logged separately).

---

## Problem 3: ContextSnapshot Exists But Isn't Implemented

We have the dataclass defined in `database_context.py`:

```python
@dataclass
class ContextSnapshot:
    snapshot_id: str
    signal_id: str
    session_id: str
    created_at: datetime
    data_as_of: datetime
    sources_status: Dict[str, SourceStatus]
    gaps: List[str]
    confidence_adjustment: float
    explanation_text: str
    # (no methods to populate these)
```

But it's never instantiated. The three core methods that would make it useful are stubbed:

- `get_or_create_snapshot()` — entry point to get context for a signal
- `fetch_with_freshness_check()` — decide if data is stale
- `_calculate_adjustment()` — lower confidence if data is missing

**Why it matters:**

Without this, we can't implement session scoping (same user, same conversation = same snapshot, faster response). Every explain request does a fresh fetch, making the first request slow and cache misses slow.

More importantly: no visibility into "which data sources were available when this explanation was generated?" If EIA data was stale or Congress.gov was down, the explanation is less reliable—but the response doesn't reflect that.

**Phase 1 fix:**

Implement the three core methods:

1. **`get_or_create_snapshot(signal, session_id)`**
   - Check if this signal was already explained in the current session
   - If yes, return cached snapshot (instant response)
   - If not, create new snapshot:
     - Fetch data from Tier 1 sources synchronously (critical)
     - Attempt Tier 2–3 sources asynchronously (optional)
     - Record success/failure for each source in `sources_status`
     - Calculate confidence adjustment
     - Save to disk (for replay and calibration)
     - Cache in-memory for session duration

2. **`fetch_with_freshness_check(source_name, snapshot_age)`**
   - Load DataSourceConfig for the source (update frequency, freshness threshold)
   - If on a fixed schedule (e.g., "EIA publishes Tuesdays at 10 AM"), return precomputed
   - If threshold is exceeded and source is stale, query the database
   - If fetch fails, return cached/fallback with error status
   - Return (data, status)

3. **`_calculate_adjustment(context)`**
   - Start with confidence = 1.0
   - Tier 1 source missing → -0.15 (critical)
   - Each Tier 2–3 source missing → -0.05 per source (max -0.25)
   - Return adjusted confidence

**Success metric:** Repeated explain requests for the same signal in the same session complete in <100ms p95 (cache hit). Explanation response includes `confidence_adjustment` field reflecting data gaps.

---

## Problem 4: LLM Output Formatting Not Enforced

The template for prompting the LLM exists in documentation, but the actual prompt is loose:

```
You are a Gambling Meteorologist...
[RAG context]
[Signal data]
Explain this signal.
```

The LLM returns free-form text. There's no guarantee it addresses the 8 steps in order, or at all.

**Why it matters:**

Parsing a free-form narrative requires brittle NLP (sentence splitting, intent detection). It's easy to misinterpret. Worse: we can't validate that the explanation is complete—did the LLM skip Steps 2 and 4? We won't know.

**Phase 1 fix:**

Structure the prompt to enforce structured output:

```
Step 1: Reference Class Lookup
[Insert reference class data]
Your task: Explain how this signal compares to similar historical trades.

Step 2: Ensemble Aggregation
[Insert ensemble voting data]
Your task: Explain which models agreed and which disagreed.

...

Step 8: Calibration
[Insert recent forecast accuracy]
Your task: Comment on how well our past explanations have aged.
```

Then parse the response by splitting on "Step N:" markers and mapping each section to the corresponding ExplanationData field.

If parsing fails, return a partial explanation with an error status instead of silently dropping data.

**Success metric:** 100% of LLM responses parse successfully into all 8 steps. If parsing fails, error is logged with correlation ID and fallback is used.

---

## Problem 5: No Retrieval Testing/Override

`retrieval_pipeline.py` supports both LanceDB and Milvus, but you can't:
- Inject test documents
- Force retrieval to return a fixed set
- Test "given these 3 documents, does the LLM generate a good explanation?"

**Why it matters:**

Without this, testing explanation quality requires:
1. Spinning up Milvus or LanceDB
2. Populating it with real documents
3. Running the full pipeline
4. Checking the output

That's slow. In CI/CD, it might not run at all because Milvus isn't available.

**Phase 1 fix:**

Add environment variable override:

```python
RAG_RETRIEVAL_MODE = os.getenv("RAG_RETRIEVAL_MODE", "normal")

if RAG_RETRIEVAL_MODE == "test":
    # Load from test_documents.json instead of LanceDB
    documents = load_test_documents("test_documents.json")
elif RAG_RETRIEVAL_MODE == "mock":
    # Return fixed set (for CI/CD)
    documents = [
        Document(doc_id="mock_1", title="Test", content="...", source="test"),
        Document(doc_id="mock_2", title="Test", content="...", source="test"),
    ]
else:
    # Normal retrieval from LanceDB
    documents = self.lance.search(embedding)
```

Now you can:
- Run `RAG_RETRIEVAL_MODE=mock pytest` for fast unit tests
- Run `RAG_RETRIEVAL_MODE=test pytest` with realistic documents
- Run `RAG_RETRIEVAL_MODE=normal` in production

**Success metric:** Explanation pipeline passes full integration tests without requiring external services.

---

## Phase 1 Checklist

**RAG Engine (Rust):**
- [ ] Modify `init_rag_engine()` to wait for first document indexed
- [ ] Keep `RAG_STATUS = 1` until DocumentStore creation succeeds
- [ ] Add 30-second timeout with degraded mode fallback
- [ ] Log initialization progress (indexing started, first document indexed, ready)

**Explanation Data (Rust/Python):**
- [ ] Expand `ExplanationData` struct to include all 8 steps as explicit fields
- [ ] Define `ReferenceClassData`, `EnsembleData`, `BayesianData`, `ScenarioData`, `ExpectedValueData`, `RiskAssessmentData` structs
- [ ] Update `explain_trading_signal` to populate all 8 fields
- [ ] Include 8-step data in API response (not just explanation text)

**Context Snapshot (Python):**
- [ ] Implement `ContextSnapshot.get_or_create_snapshot()`
- [ ] Implement `ContextSnapshot.fetch_with_freshness_check()`
- [ ] Implement `ContextSnapshot._calculate_adjustment()`
- [ ] Add `DataSourceConfig` registry with tier, freshness threshold, update pattern per source
- [ ] Persist snapshots to disk in `research/logs/` for replay

**LLM Prompting (Python):**
- [ ] Restructure prompt to explicitly request 8-step breakdown
- [ ] Add parsing logic to extract each step from LLM response
- [ ] Map parsed steps to `ExplanationData` fields
- [ ] Log parsing errors with signal ID and correlation trace

**Retrieval Pipeline (Python):**
- [ ] Add `RAG_RETRIEVAL_MODE` environment variable support
- [ ] Implement "test" mode to load from JSON file
- [ ] Implement "mock" mode for CI/CD
- [ ] Create `test_documents.json` with representative documents

---

## Phase 1 Success Metrics

**Initialization:**
- Startup: "RAG ready" only after first document indexed
- Measure: Initial `explain_trading_signal` request receives ≥3 documents in context
- Timeout: If not ready in 30s, log warning and use fallback

**Explanation Completeness:**
- Response includes all 8 steps (or error if not available)
- Reference class name, ensemble weights, Bayesian confidence changes, scenarios, etc. are observable
- Measure: `len(explanation.steps) == 8` or error logged

**Session Caching:**
- Same signal, same session: <100ms p95 latency (second request)
- Measure: `ContextSnapshot` cache hit rate >70%
- Different signal or different session: <2s p95 latency (full fetch + LLM)

**Data Transparency:**
- Response includes `data_as_of` timestamp and `sources_status` dict
- User sees which data sources succeeded/failed
- Confidence adjusted by `confidence_adjustment` factor
- Measure: Response includes all three fields

**Retrieval Testability:**
- Full integration test passes with `RAG_RETRIEVAL_MODE=mock`
- Unit tests run in <1 second without external services
- Measure: CI/CD pipeline completes in <3 minutes (was: blocked on Milvus)

---

## What's Next

These five problems are interconnected: you can't test retrieval properly without a mock mode, but then you need structured explanation output to validate that mock documents are being used correctly. You can't verify initialization worked without checking that ContextSnapshot has data. You can't implement session scoping without ContextSnapshot methods.

Phase 1 closes these gaps in one coordinated push.

**Phase 2** will focus on observability: how do we know when things go wrong? What happens when a data source fails? How do we track explanation accuracy over time? That'll involve structured logging, correlation IDs threading through the entire stack, and a dashboard showing system health.

**Phase 3** is design: the current Tauri app is a monolith optimized for desktop. Phase 3 responds to "what if the system worked on tablets, or even phones?"—which means responsive design, accessible keyboard navigation, and persistent state across restarts.

All three phases are anchored to a single principle: **the gap between documented design and code is where bugs live**. Each phase shrinks that gap.

---

Next post: Observability & CI/CD.
