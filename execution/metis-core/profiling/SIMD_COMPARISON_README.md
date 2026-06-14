# SIMD Benchmark Comparison Suite

Isolated testing framework to compare SIMD performance between Windows and WSL with system state monitoring.

## Problem

Previous SIMD benchmarks showed performance regressions, but it was unclear whether the differences were:
- **Algorithmic** (actual SIMD code issue)
- **Environmental** (CPU throttling, frequency scaling, system load)
- **Platform-specific** (Windows vs WSL architecture differences)

## Solution

This suite runs 3 isolated trials on each platform, monitoring:
- Benchmark performance (Criterion criterion output)
- CPU frequency during runs
- Memory usage and allocation
- System load and process count

## Quick Start

### Step 1: Run Windows Baseline

```powershell
# On Windows PowerShell
cd c:\Users\legot\Metis\profiling
.\run_simd_comparison.ps1 -Trials 3
```

**What it does:**
- Clears Criterion cache before each trial
- Monitors CPU MHz, memory, and system load in parallel with benchmarks
- Logs raw benchmark output
- Saves results to `simd_trials_windows_<timestamp>/`

**Output files:**
- `benchmark_results.csv` - Timing data for each benchmark
- `system_metrics.csv` - CPU/memory/load sampled every 500ms during run
- `trial_N_raw.txt` - Raw Criterion output
- `run.log` - Timestamped execution log

### Step 2: Run WSL Baseline

```bash
# On WSL bash
cd /mnt/c/Users/legot/Metis/profiling
bash wsl-simd-comparison.sh --trials 3
```

**Prerequisites:**
- cargo in PATH
- Rust toolchain available

**Output:** Same structure as Windows, but in `simd_trials_wsl_<timestamp>/`

### Step 3: Compare Results

```bash
# From Windows PowerShell or WSL bash
python3 c:/Users/legot/Metis/profiling/compare_simd_results.py \
    simd_trials_windows_2026-06-02_120000 \
    simd_trials_wsl_2026-06-02_140000
```

**Output:**
- Formatted comparison table (mean ± stdev for each benchmark)
- System state analysis (CPU MHz, memory, load per trial)
- Statistical difference (% faster/slower)
- Interpretation guide
- JSON export for further analysis

## Understanding the Results

### Example Output

```
BENCHMARK RESULTS (ns = nanoseconds)
───────────────────────────────────────────────────────────────────────────────
Benchmark                      Windows Mean           WSL Mean               Difference
───────────────────────────────────────────────────────────────────────────────
simd_normalization/scalar      160.50 ± 2.30         165.20 ± 4.50         +2.9% ⚪
simd_normalization/simd_avx2   24.50 ± 1.10          28.30 ± 2.40          +15.5% 🔴
euclidean_distance/scalar      2620.00 ± 85.40       2710.00 ± 120.00      +3.4% ⚪
euclidean_distance/simd_avx2   3201.00 ± 110.00      3450.00 ± 180.00      +7.8% 🔴
```

**Key Indicators:**
- 🟢 **Green (<-5%)**: WSL is actually faster (likely measurement noise)
- ⚪ **Gray (±5%)**: Within statistical margin of error
- 🔴 **Red (>+5%)**: WSL is meaningfully slower - investigate system state

### System State Analysis

```
Trial_1:
───────
  Windows CPU: 3600 MHz (range: 3600-3600) ← Constant frequency = good
  Windows Memory: 42% used
  Windows Load: max 0.8

  WSL CPU: 2400 MHz (range: 1800-2800) ← Varying = thermal throttling
  WSL Memory: 68% used ← Higher memory pressure
  WSL Load: max 2.1 ← More background activity
```

**What to look for:**
1. **CPU Frequency variance**: High variance (1800-2800 MHz) = frequency scaling interference
2. **Memory pressure**: If > 80%, system swapping might occur
3. **Load average**: If > core_count/2, background processes interfering
4. **Trial-to-trial consistency**: If Trial 1-3 results differ, system is not isolated

## Troubleshooting

### High variance within the same platform

**Symptom:** Trial 1 shows 24.5 ns, Trial 3 shows 28.1 ns on same platform

**Causes:**
- Windows Update running in background
- Antivirus scanning
- Docker/WSL2 Hyper-V contention
- Thermal throttling (CPU overheating)

**Solutions:**
1. Stop Windows Update: `Stop-Service wuauserv`
2. Close browser/IDEs during benchmark
3. Run on battery power to disable turbo (more consistent frequency)
4. Check CPU temperature: should be < 70°C during run

### WSL consistently slower

**Symptom:** All WSL benchmarks are +10-20% slower than Windows

**Causes:**
1. WSL2 Hyper-V overhead (inherent)
2. CPU frequency scaling governors differ
3. Memory allocation strategy

**Solutions:**
1. Check `.wslconfig` memory limit - ensure it's not restrictive
2. Force WSL to run on Performance plan (Windows: Control Panel → Power Options → High Performance)
3. Test with native Linux if available (to isolate WSL2 vs Linux differences)

### CPU frequency stuck low

**On WSL:**
```bash
# Check current frequency
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq

# Check available governors
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors

# Try performance governor (requires sudo in some WSL distros)
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

### Criterion regression detection interfering

If you want truly independent trials without Criterion comparing to history:

```powershell
# Clear all Criterion data between trials
rm -r metis-core/target/criterion/

# Or use Criterion's --baseline flag to reset:
cargo bench --bench simd_vectorization -- --baseline baseline_<timestamp>
```

## Interpreting Regression Percentages

When you see: `change: [+20.962% +27.031% +33.272%]`

This is **Criterion's confidence interval** for how much performance changed from the *previous recorded baseline*. This is different from platform comparison:

- **For isolated trials**: Delete `target/criterion/` so each trial starts fresh
- **For regression detection**: Keep `target/criterion/` to track if optimizations worked

## Data Files Reference

### benchmark_results.csv
```
Trial,Benchmark,Time_NS,Lower_NS,Upper_NS
1,simd_normalization/scalar,160.55,156.58,164.79
1,simd_normalization/simd_avx2,24.47,23.30,25.75
```

Column meanings:
- `Time_NS`: Mean execution time in nanoseconds
- `Lower_NS`, `Upper_NS`: 95% confidence interval bounds

### system_metrics.csv
```
Timestamp,Trial,Elapsed_Sec,CPU_MHz,Memory_Used_GB,Memory_Percent,Process_Count,Load_Avg
2026-06-02 12:00:15,1,0,3600,8.2,42.1,124,0.3
2026-06-02 12:00:15,1,1,3600,8.3,42.5,124,0.4
```

Column meanings:
- `Elapsed_Sec`: Seconds into the benchmark run
- `CPU_MHz`: Current CPU frequency
- `Memory_Percent`: System memory utilization %
- `Load_Avg`: System load average (Linux-like measure of runnable processes)

## Next Steps After Comparison

### If differences are > 10% and correlate with system state:

1. **Isolate further**: Run trials at different times, different processes open
2. **Check assembly**: Verify SIMD code is actually being generated
   ```
   cargo build --release && objdump -d target/release/deps/... | grep vpaddq
   ```
3. **Test on different hardware**: If you have access to clean machine

### If differences are within 5% or correlate with Criterion regression:

1. **Results are valid**: Platform difference is minor or measurement noise
2. **Focus elsewhere**: Look at actual algorithmic optimizations, not platform
3. **Document baseline**: Save these results as golden reference

## Files in This Suite

- `run_simd_comparison.ps1` - Windows trial runner
- `wsl-simd-comparison.sh` - WSL trial runner
- `compare_simd_results.py` - Analysis and comparison script
- `SIMD_COMPARISON_README.md` - This file

## Automation

To run full comparison periodically:

```powershell
# Windows
$TS = (Get-Date -Format "yyyy-MM-dd")
& .\run_simd_comparison.ps1 -Trials 3 | Tee-Object "simd_results_$TS.log"
wsl bash wsl-simd-comparison.sh --trials 3
python3 compare_simd_results.py simd_trials_windows_* simd_trials_wsl_*
```
