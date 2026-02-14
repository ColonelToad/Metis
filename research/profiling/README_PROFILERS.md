# Metis Pipeline Profiling Guide

Three complementary profilers to measure real bottlenecks in your signal generation pipeline.

## Quick Start

```powershell
# Position in research directory
cd C:\Users\legot\Metis\research

# Run the profilers in order to understand your system
python profiling/profile_ingestion_detail.py      # 10-30 minutes (API dependent)
python profiling/profile_signal_latency.py        # 2-5 minutes (uses cached data)
python profiling/profile_full_pipeline.py         # 20-60 minutes (complete pipeline)
```

## Three Profilers: What They Measure

### 1. **profile_ingestion_detail.py** ⏱️ Data Source Latency
**Best for:** Understanding which APIs are slow and parallelization potential

**What it measures:**
- Individual API fetch time (EIA, LMP, FRED, Congress, BLS, CME, Freight)
- Sequential vs. parallel execution comparison
- Bottleneck identification
- Cache hit rates (if applicable)

**Why run it:**
- Answers: "Which data source is slowest?"
- Answers: "How much faster if we parallelize?"
- Identifies dependencies between APIs

**Expected output (example):**
```
SEQUENTIAL (current):     6.1s
  EIA:                    1.2s
  LMP:                    2.1s  ← SLOWEST
  FRED:                   0.6s
  Congress:               0.4s
  BLS:                    0.5s
  CME:                    0.3s
  Freight:                1.0s

PARALLEL (potential):     2.1s
  → Speedup: 3x (limited by slowest = LMP)
```

**Typical runtime:** 10-30 minutes (depends on API response times and network)

**How to interpret:**
- If `Sequential >> Parallel`: **Parallelization HIGHLY RECOMMENDED**
- Look at slowest API - that's your bottleneck
- Check if there are dependencies (some APIs might need others' data)

---

### 2. **profile_signal_latency.py** 🚀 Real-Time Signal Generation
**Best for:** Measuring how fast you can generate a signal when needed NOW

**What it measures:**
- Feature engineering latency (loading + transforming data)
- Model preprocessing time
- Inference time
- Signal generation time
- **Does NOT include data ingestion** (assumes data is fresh in DB)

**Why run it:**
- Answers: "How fast can I generate a signal right now?"
- Shows which part of signal path is slow
- Realistic measurement of real-time signal latency

**Expected output (example):**
```
engineer_features:       0.5s  (50%)
prep_daily_features:     0.2s  (20%)
prep_lowfreq_features:   0.15s (15%)
model_predict:           0.10s (10%)
signal_generation:       0.05s (5%)
─────────────────────────────────
TOTAL:                   1.0s
```

**Typical runtime:** 2-5 minutes (uses data already in DB)

**With fresh ingestion:**
```
python profiling/profile_signal_latency.py --fresh-ingest

# Adds:
ingest_fresh:            6.1s
+ signal path:           1.0s
─────────────────────────────────
END-TO-END:              7.1s
```

**How to interpret:**
- If `< 1s`: Real-time signals are feasible
- If `1-5s`: Borderline, consider optimizations
- If `> 5s`: Need optimization before using real-time signals
- Look at which phase dominates (feature eng? model? signal gen?)

---

### 3. **profile_full_pipeline.py** 📊 Complete System Profile
**Best for:** Understanding your entire system from end-to-end

**What it measures:**
- All three stages together
- Per-API latency breakdown
- Per-feature-stage latency breakdown
- Memory usage and peak memory
- Function-level profiling (cProfile)
- Detailed bottleneck analysis

**Why run it:**
- Most comprehensive view
- Gives you the high-level picture
- Outputs detailed cProfile for finding hot functions
- Saves JSON results for tracking over time

**Expected output (example):**
```
TIMING BREAKDOWN:
  Data Ingestion (sequential):   6.1s  (87%)
  Feature Engineering:           0.5s  (7%)
  Model Inference:               0.4s  (6%)
  ──────────────────────────────────
  TOTAL END-TO-END:             7.0s (100%)

BOTTLENECK: Data ingestion is 87% of total time
  → Opportunity: Parallelize API calls (2-5x speedup)

PER-API BREAKDOWN:
  LMP/CAISO:                     2.1s
  EIA:                           1.2s
  Freight:                       1.0s
  ...
```

**Typical runtime:** 20-60 minutes (everything)

**How to interpret:**
- Gives you the percentage breakdown
- Shows where optimization ROI is highest
- Identifies if ingestion or features or inference is the bottleneck

---

## Running Order & Interpretation Flow

```
┌─────────────────────────────────────────┐
│ 1. profile_ingestion_detail.py          │
│    (Understand API bottlenecks)         │
└──────────────────┬──────────────────────┘
                   ↓
           Is parallelization
           possible? (check dependencies)
                   ↓
┌──────────────────┴──────────────────────┐
│ 2. profile_signal_latency.py            │
│    (How fast for on-demand signals?)    │
└──────────────────┬──────────────────────┘
                   ↓
           Understand feature vs.
           model vs. signal bottleneck
                   ↓
┌──────────────────┴──────────────────────┐
│ 3. profile_full_pipeline.py             │
│    (Complete picture + recommendations) │
└──────────────────────────────────────────┘
```

## Expected Results & What They Mean

### Scenario 1: Data Ingestion is the Bottleneck (Most Likely)
**What you'll see:**
- Ingestion > 50% of total time
- Parallel version is 2-5x faster
- Feature engineering is < 20% of total

**Recommendation:**
- Parallelize API calls in `run_all_ingesters.py` (8-10 hours)
- Add caching with TTL (4-6 hours)
- Expect: **3-5x faster ingestion**

### Scenario 2: Feature Engineering is the Bottleneck
**What you'll see:**
- Feature engineering > 30% of total time
- Many rolling stats or complex transforms
- Database queries taking a long time

**Recommendation:**
- Optimize SQL queries (add indexes on date)
- Vectorize Python loops
- Consider moving to Rust for heavy transforms
- Expect: **3-10x faster feature loading**

### Scenario 3: Model Inference is the Bottleneck
**What you'll see:**
- Model inference > 20% of total time
- Latency mostly in `model_predict` phase

**Recommendation:**
- Quantize model (FP32 → FP16): 2x speedup
- Use ONNX Runtime: 1.5-2x speedup
- Batch predictions: 2-5x speedup for multiple signals
- Expect: **2-5x faster inference**

### Scenario 4: Already Well-Optimized
**What you'll see:**
- All stages < 1 second
- No obvious bottleneck

**Recommendation:**
- Probably don't need further optimization
- Focus on feature richness instead of speed
- Consider incremental updates for caching

---

## Output Files

Each profiler saves results to `profiling/`:

```
profiling/
├── profile_ingestion_detail.py          # Script
├── profile_signal_latency.py            # Script
├── profile_full_pipeline.py             # Script
│
└── results/
    ├── pipeline_profile_20260211_120534.json    # Full pipeline results
    ├── signal_latency_20260211_120535.json      # Signal latency results
    └── ...
```

JSON format includes:
- Exact timings (all phases and sub-phases)
- Data counts (rows returned, features created)
- Memory usage (current and peak)
- Error messages (if any component failed)
- Mode (DEV vs REAL)

---

## What Data You Should Collect

For optimization planning, collect these numbers:

### Before Optimization
- [ ] Sequential ingestion time
- [ ] Parallel ingestion time (potential)
- [ ] Signal generation latency (without ingestion)
- [ ] Feature engineering as % of total
- [ ] Model inference as % of total
- [ ] Which single API is slowest
- [ ] Peak memory usage

### For Comparison (After Each Optimization)
- [ ] Run profilers again same way
- [ ] Save JSON results
- [ ] Track speedup for each phase
- [ ] Compare against baseline

---

## Tips for Accurate Profiling

1. **Run on representative data**
   - Use actual database (not synthetic)
   - Use recent dates (not just first 1000 rows)

2. **Be aware of caching effects**
   - First run: API calls might be slow
   - Second run: Might hit caches
   - Run twice if you want "typical" numbers

3. **Network conditions matter**
   - Results vary with internet speed
   - Try running profilers at consistent time

4. **Database state matters**
   - If database is empty, results might be misleading
   - Run data ingesters once first

5. **For consistency**
   - Close other applications
   - Run in DEV mode (doesn't hit real APIs)
   - Run at same time of day

---

## Next Steps Based on Results

Once you have profiling data:

1. **Post JSON output** from profilers
2. **Share the bottleneck** (which phase is slowest)
3. **I'll give you specific optimizations** for YOUR system

Example good output to share:
```
{"timings": {
  "ingest_total_sequential": 6.1,
  "ingest_eia": 1.2,
  "ingest_lmp": 2.1,
  "features_total": 0.5,
  "inference_total": 0.4,
  "total_signal_latency": 0.9
}}
```

---

## Troubleshooting

### "API call failed" in ingestion profiler
- Normal if in DEV mode (synthetic data instead)
- Use `--fresh-ingest` flag with real API keys set

### "Model files not found" in inference profiler
- Expected if models haven't been trained yet
- Profiler will skip and estimate timing

### Profiler hangs on a specific API
- The API might be slow or unreachable
- Ctrl-C to stop, check `run_ingestion.py` for that API's code
- Some APIs have rate limits

### Results vary widely between runs
- Network latency varies
- APIs might have variable response time
- Run 3x and take average

---

## Questions to Ask After Profiling

1. What's the percentage breakdown? (ingest vs features vs model)
2. Which single API is slowest?
3. How much faster with parallelization?
4. Is any phase > 50% of total?
5. What's the fastest achievable time if we optimize the bottleneck?

---

Happy profiling! 📊
