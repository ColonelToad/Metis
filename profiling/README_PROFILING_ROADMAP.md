# Hardware Profiling Roadmap: Windows → WSL → RT-Thread

**Date**: February 10, 2026  
**Status**: Scripts ready for execution  
**Goal**: Establish cross-platform baselines before RT-thread optimization

---

## Overview

You now have two profiling scripts:
1. **Windows Baseline**: `profiling/windows-baseline.ps1` (PowerShell)
2. **WSL Baseline**: `profiling/wsl-baseline.sh` (Bash)

These scripts will measure the same benchmarks on both platforms, revealing platform-specific overhead and informing RT-thread optimization decisions.

---

## Quick Start

### Phase A: Windows Baseline (Today, ~30 min)

```powershell
cd c:\Users\legot\Metis

# Run Windows profiling
powershell -ExecutionPolicy Bypass -File profiling/windows-baseline.ps1 -Verbose

# Optional: Generate flamegraph CPU profile
powershell -ExecutionPolicy Bypass -File profiling/windows-baseline.ps1 -Verbose -Profile
```

**Output**: Files in `profiling/` directory:
- `windows_simd_YYYY-MM-DD_HHMMSS.txt` - SIMD benchmark details
- `windows_lockfree_YYYY-MM-DD_HHMMSS.txt` - Lock-free queue benchmark
- `windows_bridge_YYYY-MM-DD_HHMMSS.txt` - FFI latency measurements
- `windows_tests_YYYY-MM-DD_HHMMSS.log` - All 27 tests passing
- `windows_flamegraph_YYYY-MM-DD_HHMMSS.svg` - CPU hotspots (optional)

**Expected Results**:
- ✅ All tests pass (27/27)
- ✅ SIMD correlation: ~30ns per calculation
- ✅ Lock-free queue: ~28ns push latency
- ✅ FFI bridge: ~139ns round-trip

### Phase B: WSL Baseline (Next, ~45 min)

```bash
# Open WSL terminal
wsl

# Navigate to project (auto-mounted from Windows)
cd /mnt/c/Users/legot/Metis

# Make script executable
chmod +x profiling/wsl-baseline.sh

# Run WSL profiling (installs Rust if needed)
./profiling/wsl-baseline.sh
```

**Output**: Same metrics as Windows, in WSL environment:
- `wsl_simd_YYYY-MM-DD_HHMMSS.txt`
- `wsl_lockfree_YYYY-MM-DD_HHMMSS.txt`
- `wsl_bridge_YYYY-MM-DD_HHMMSS.txt`
- `wsl_perf_YYYY-MM-DD_HHMMSS.txt` (performance counters, if `perf` available)

---

## What to Measure / What Results Mean

### SIMD Vectorization Benchmark

**Key Metric**: Time per correlation calculation

```
Baseline (scalar):    ~200-300 nanoseconds
SIMD (AVX2):          ~30-50 nanoseconds
Expected speedup:     6-10x
```

**What it tells you**:
- Windows vs WSL: Expect within 5% (mostly CPU-bound, not OS-dependent)
- If WSL is slower by >15%: indicates memory bandwidth issue
- If WSL is faster: WSL scheduler may be better for SIMD workloads

### Lock-Free Fusion Benchmark

**Key Metric**: Queue push latency under 1-4 concurrent writers

```
Uncontended:          ~5 nanoseconds
Contended (4 threads): ~28 nanoseconds  (our baseline)
If using mutex:        ~75 nanoseconds
```

**What it tells you**:
- Windows vs WSL: Expect within 10% (both should show scalability)
- If variance (p95-p50) differs significantly: kernel scheduler differences
- High variance on one platform = candidate for RT-thread optimization

### Python-Rust Bridge Latency

**Key Metric**: Time to cross Python→Rust→Python boundary

```
Current:              ~139 nanoseconds
Target Phase 2:       <50 nanoseconds
Target Phase 3:       <5 nanoseconds
```

**What it tells you**:
- Windows vs WSL: Expect within 20% (GIL overhead should be similar)
- If WSL is slower by >30%: indicates GIL contention or scheduling
- Variance (p99-p50): this is where RT-thread helps

---

## Analysis Workflow

### Step 1: Collect Both Baselines
```
Windows baseline ✅ → Compare → WSL baseline ✅
```

### Step 2: Create Comparison Document
Create `profiling/CROSS_PLATFORM_RESULTS.md`:

```markdown
# Windows vs WSL Benchmark Comparison

| Metric | Windows | WSL | Difference | Notes |
|--------|---------|-----|-----------|-------|
| SIMD correlation (ns) | 32 | 31 | -3% | Within variance |
| Lock-free push (ns) | 28 | 30 | +7% | WSL scheduler overhead |
| FFI bridge (ns) | 139 | 155 | +12% | GIL contention? |
```

### Step 3: Identify Bottleneck for RT-Thread

Based on comparison results, answer:
1. **Which platform handles concurrency better?** (Windows or WSL)
2. **Which metric has highest variance?** (p99-p50 delta)
3. **Which thread is blocking others?** (from flamegraph)

Example findings:
- **Finding A**: FFI bridge on Windows has 200ns p99 but 139ns p50 → 60ns variance
  - **Action**: RT-thread pinning for signal generation thread (reduce scheduling variance)
- **Finding B**: Lock-free queue on WSL shows contention scaling → slower with >2 threads
  - **Action**: NUMA-aware pinning (separate threads to different CPU sockets)
- **Finding C**: Both platforms identical performance
  - **Action**: Skip platform-specific optimization, focus on algorithm-level improvements

### Step 4: RT-Thread Scoping

Once you identify the bottleneck, decide:

```
Option A: Light RT-Thread
├─ Pin signal generation thread to isolated CPU core
├─ Set PRIORITY_REALTIME
└─ Expect: 3-5x reduction in latency variance

Option B: Full RTOS
├─ Implement rt-thread for both signal + execution threads
├─ Memory-mapped queues
└─ Expect: 10-20x reduction in variance, <5% throughput loss
```

---

## Expected Timeline

### Week 1 (This week)
- ✅ Fix ingesters (DONE)
- ✅ Write hardware blog post (DONE)
- ⏳ **TODAY**: Run Windows baseline (~30 min)

### Week 2
- Run WSL baseline (~45 min)
- Analyze cross-platform differences (~1 hour)
- Document findings in `CROSS_PLATFORM_RESULTS.md` (~1 hour)
- Decide RT-thread scope

### Week 3
- Implement RT-thread for chosen thread (~6-8 hours if option A)
- Measure improvement vs baselines
- Publish results in blog post update

**Total time**: ~12-15 hours of active work (mostly waiting for benchmarks to run)

---

## Troubleshooting

### Windows Script Issues

**Error**: "cargo not found"
```powershell
# Install Rust
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri https://sh.rustup.rs/ -OutFile rustup-init.exe
./rustup-init.exe
```

**Error**: "Benchmark failed with timeout"
```powershell
# Increase timeout or run single benchmark
cargo bench --bench simd_vectorization --release --
```

### WSL Script Issues

**Error**: "Script permission denied"
```bash
chmod +x profiling/wsl-baseline.sh
./profiling/wsl-baseline.sh
```

**Error**: "Rust not found in WSL"
- Script will auto-install, but if it fails:
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source $HOME/.cargo/env
```

**Error**: "perf not available"
- Optional for baseline, helps with bottleneck analysis
```bash
sudo apt-get install linux-tools-generic
```

---

## What's Next After Baselines Are Collected

1. **Compare Results**: Are Windows and WSL latencies similar or significantly different?
2. **Identify Bottleneck**: Which code path has highest variance?
3. **RT-Thread Design**: Decide scope (single thread vs full RTOS)
4. **Implementation**: 6-8 hours of coding + testing
5. **Blog Post Update**: Document results and lessons learned

---

## Key Files

| File | Purpose |
|------|---------|
| `profiling/windows-baseline.ps1` | Capture Windows hardware baselines |
| `profiling/wsl-baseline.sh` | Capture WSL/Linux hardware baselines |
| `profiling/CROSS_PLATFORM_RESULTS.md` | (You'll create) Comparison analysis |
| `docs/_posts/2026-02-10-hardware-optimization-phase-1.md` | Phase 1 blog post (complete) |

---

## Questions Before You Run?

- Want to bypass certain benchmarks? Edit script to comment out sections
- Want fresher baselines? Use `-Clean` flag (PowerShell only) to `cargo clean` first
- Want to profile specific function? Check Criterion.rs filter syntax: `cargo bench -- --filter pattern`

---

**Ready to run?** Execute the Windows baseline script first. Once complete, upload results and we'll schedule WSL profiling.
