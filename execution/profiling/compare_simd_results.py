#!/usr/bin/env python3
"""
Compare SIMD benchmark results between Windows and WSL trials.
Analyzes performance differences and system state correlations.

Usage:
    python3 compare_simd_results.py <windows_trial_dir> <wsl_trial_dir>
    
Example:
    python3 compare_simd_results.py \
        simd_trials_windows_2026-06-02_120000 \
        simd_trials_wsl_2026-06-02_140000
"""

import csv
import sys
import json
from pathlib import Path
from statistics import mean, stdev, StatisticsError
from dataclasses import dataclass

@dataclass
class BenchmarkResult:
    trial: int
    benchmark: str
    time_ns: float
    lower_ns: float
    upper_ns: float
    
    @property
    def margin_ns(self):
        """Confidence interval width"""
        return self.upper_ns - self.lower_ns
    
    @property
    def margin_percent(self):
        """Confidence interval as % of mean"""
        return (self.margin_ns / self.time_ns) * 100 if self.time_ns else 0

@dataclass
class SystemMetric:
    timestamp: str
    trial: int
    elapsed_sec: int
    cpu_mhz: float
    memory_free_gb: float
    memory_used_percent: float
    process_count: int
    load_avg: float

def read_benchmark_results(csv_path):
    """Parse benchmark CSV file"""
    results = []
    if not Path(csv_path).exists():
        print(f"Warning: {csv_path} not found")
        return results
    
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                results.append(BenchmarkResult(
                    trial=int(row.get('Trial', 0)),
                    benchmark=row.get('Benchmark', ''),
                    time_ns=float(row.get('Time_NS', 0)),
                    lower_ns=float(row.get('Lower_NS', 0)),
                    upper_ns=float(row.get('Upper_NS', 0))
                ))
            except ValueError:
                continue
    
    return results

def read_system_metrics(csv_path):
    """Parse system metrics CSV file"""
    metrics = {}
    if not Path(csv_path).exists():
        print(f"Warning: {csv_path} not found")
        return metrics
    
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                trial = int(row.get('Trial', 0))
                if trial not in metrics:
                    metrics[trial] = []
                
                # Handle different column names (Windows vs WSL)
                cpu_mhz = float(row.get('CPU_MHz', row.get('cpu_mhz', 0)))
                mem_used = float(row.get('Memory_Used_GB', row.get('memory_used_gb', 0)))
                mem_percent = float(row.get('Memory_Used_Percent', row.get('memory_used_percent', 0)))
                proc_count = int(row.get('Process_Count', row.get('process_count', 0)))
                load_avg = float(row.get('Load_Avg', row.get('load_avg', 0)))
                
                metrics[trial].append(SystemMetric(
                    timestamp=row.get('Timestamp', ''),
                    trial=trial,
                    elapsed_sec=int(row.get('Elapsed_Sec', 0)),
                    cpu_mhz=cpu_mhz,
                    memory_free_gb=mem_used,  # Note: CSV has confusing naming
                    memory_used_percent=mem_percent,
                    process_count=proc_count,
                    load_avg=load_avg
                ))
            except ValueError:
                continue
    
    return metrics

def aggregate_by_benchmark(results):
    """Group results by benchmark name"""
    by_bench = {}
    for result in results:
        if result.benchmark not in by_bench:
            by_bench[result.benchmark] = []
        by_bench[result.benchmark].append(result)
    return by_bench

def calculate_stats(values):
    """Calculate mean, stdev, min, max"""
    if not values:
        return None
    
    m = mean(values)
    try:
        s = stdev(values) if len(values) > 1 else 0
    except StatisticsError:
        s = 0
    
    return {
        'mean': m,
        'stdev': s,
        'min': min(values),
        'max': max(values),
        'count': len(values)
    }

def compare_benchmarks(windows_results, wsl_results):
    """Compare benchmark performance between platforms"""
    
    wins_by_bench = aggregate_by_benchmark(windows_results)
    wsl_by_bench = aggregate_by_benchmark(wsl_results)
    
    all_benches = set(wins_by_bench.keys()) | set(wsl_by_bench.keys())
    
    comparison = {}
    for bench_name in sorted(all_benches):
        win_times = [r.time_ns for r in wins_by_bench.get(bench_name, [])]
        wsl_times = [r.time_ns for r in wsl_by_bench.get(bench_name, [])]
        
        win_stats = calculate_stats(win_times)
        wsl_stats = calculate_stats(wsl_times)
        
        diff_percent = None
        if win_stats and wsl_stats:
            diff_percent = ((wsl_stats['mean'] - win_stats['mean']) / win_stats['mean']) * 100
        
        comparison[bench_name] = {
            'windows': win_stats,
            'wsl': wsl_stats,
            'difference_percent': diff_percent,
            'faster_platform': 'WSL' if diff_percent and diff_percent < 0 else 'Windows'
        }
    
    return comparison

def analyze_system_state(win_metrics, wsl_metrics):
    """Analyze system state during benchmarks"""
    
    analysis = {}
    
    for trial in set(list(win_metrics.keys()) + list(wsl_metrics.keys())):
        win_data = win_metrics.get(trial, [])
        wsl_data = wsl_metrics.get(trial, [])
        
        if win_data:
            win_cpus = [m.cpu_mhz for m in win_data if m.cpu_mhz > 0]
            win_mems = [m.memory_used_percent for m in win_data]
            win_loads = [m.load_avg for m in win_data if m.load_avg >= 0]
            
            win_analysis = {
                'cpu_mhz_avg': mean(win_cpus) if win_cpus else None,
                'cpu_mhz_min': min(win_cpus) if win_cpus else None,
                'cpu_mhz_max': max(win_cpus) if win_cpus else None,
                'mem_percent_avg': mean(win_mems) if win_mems else None,
                'load_avg_max': max(win_loads) if win_loads else None,
            }
        else:
            win_analysis = None
        
        if wsl_data:
            wsl_cpus = [m.cpu_mhz for m in wsl_data if m.cpu_mhz > 0 and m.cpu_mhz < 10000]
            wsl_mems = [m.memory_used_percent for m in wsl_data]
            wsl_loads = [m.load_avg for m in wsl_data if m.load_avg >= 0]
            
            wsl_analysis = {
                'cpu_mhz_avg': mean(wsl_cpus) if wsl_cpus else None,
                'cpu_mhz_min': min(wsl_cpus) if wsl_cpus else None,
                'cpu_mhz_max': max(wsl_cpus) if wsl_cpus else None,
                'mem_percent_avg': mean(wsl_mems) if wsl_mems else None,
                'load_avg_max': max(wsl_loads) if wsl_loads else None,
            }
        else:
            wsl_analysis = None
        
        analysis[f'Trial_{trial}'] = {
            'windows': win_analysis,
            'wsl': wsl_analysis
        }
    
    return analysis

def print_report(comparison, system_analysis):
    """Print formatted comparison report"""
    
    print("\n" + "="*80)
    print("SIMD BENCHMARK COMPARISON: Windows vs WSL")
    print("="*80 + "\n")
    
    # Benchmark comparison
    print("BENCHMARK RESULTS (ns = nanoseconds)")
    print("-"*80)
    print(f"{'Benchmark':<30} {'Windows Mean':<18} {'WSL Mean':<18} {'Difference':<12}")
    print("-"*80)
    
    for bench_name in sorted(comparison.keys()):
        comp = comparison[bench_name]
        
        if comp['windows'] and comp['wsl']:
            win_mean = comp['windows']['mean']
            wsl_mean = comp['wsl']['mean']
            diff = comp['difference_percent']
            
            win_str = f"{win_mean:.2f} ± {comp['windows']['stdev']:.2f}"
            wsl_str = f"{wsl_mean:.2f} ± {comp['wsl']['stdev']:.2f}"
            
            if diff > 5:
                diff_str = f"WSL +{diff:.1f}% 🔴"
            elif diff < -5:
                diff_str = f"WSL -{abs(diff):.1f}% 🟢"
            else:
                diff_str = f"Within margin ⚪"
            
            print(f"{bench_name:<30} {win_str:<18} {wsl_str:<18} {diff_str:<12}")
        elif comp['windows']:
            print(f"{bench_name:<30} {comp['windows']['mean']:<18} {'[No data]':<18}")
        elif comp['wsl']:
            print(f"{bench_name:<30} {'[No data]':<18} {comp['wsl']['mean']:<18}")
    
    print("\n" + "="*80)
    print("SYSTEM STATE ANALYSIS")
    print("="*80 + "\n")
    
    for trial_name in sorted(system_analysis.keys()):
        trial_data = system_analysis[trial_name]
        
        print(f"\n{trial_name}:")
        print("-"*40)
        
        if trial_data['windows']:
            w = trial_data['windows']
            if w['cpu_mhz_avg']:
                print(f"  Windows CPU: {w['cpu_mhz_avg']:.0f} MHz (range: {w['cpu_mhz_min']:.0f}-{w['cpu_mhz_max']:.0f})")
            if w['mem_percent_avg']:
                print(f"  Windows Memory: {w['mem_percent_avg']:.1f}% used")
            if w['load_avg_max']:
                print(f"  Windows Load: max {w['load_avg_max']:.2f}")
        
        if trial_data['wsl']:
            w = trial_data['wsl']
            if w['cpu_mhz_avg']:
                print(f"  WSL CPU: {w['cpu_mhz_avg']:.0f} MHz (range: {w['cpu_mhz_min']:.0f}-{w['cpu_mhz_max']:.0f})")
            if w['mem_percent_avg']:
                print(f"  WSL Memory: {w['mem_percent_avg']:.1f}% used")
            if w['load_avg_max']:
                print(f"  WSL Load: max {w['load_avg_max']:.2f}")
    
    print("\n" + "="*80)
    print("INTERPRETATION")
    print("="*80)
    print("""
1. **Benchmark Difference > 5%**: Likely environmental (thermal throttling,
   frequency scaling, or system load). Re-run with lower system load.

2. **CPU Frequency Lower on WSL**: WSL2 may have different CPU governor
   settings. Check power profile and BIOS settings.

3. **Higher System Load on WSL**: Hyper-V overhead or background processes.
   Stop Docker, disable Windows services, or use native Linux if possible.

4. **SIMD Slower than Scalar**: Indicates either:
   - SIMD code not being compiled properly (check assembly)
   - Data not fitting in cache (memory alignment issue)
   - Criterion benchmarking artifact (data too small)
""")

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    
    win_dir = Path(sys.argv[1])
    wsl_dir = Path(sys.argv[2])
    
    print(f"Reading Windows results from: {win_dir}")
    print(f"Reading WSL results from: {wsl_dir}")
    
    # Load data
    win_results = read_benchmark_results(win_dir / "benchmark_results.csv")
    wsl_results = read_benchmark_results(wsl_dir / "benchmark_results.csv")
    
    win_metrics = read_system_metrics(win_dir / "system_metrics.csv")
    wsl_metrics = read_system_metrics(wsl_dir / "system_metrics.csv")
    
    if not win_results or not wsl_results:
        print("Error: Could not load benchmark results from one or both directories")
        sys.exit(1)
    
    # Compare
    comparison = compare_benchmarks(win_results, wsl_results)
    system_analysis = analyze_system_state(win_metrics, wsl_metrics)
    
    # Report
    print_report(comparison, system_analysis)
    
    # Save JSON for further analysis
    output_json = Path(".") / "simd_comparison_results.json"
    with open(output_json, 'w') as f:
        json.dump({
            'benchmarks': {k: {
                'windows': v['windows'],
                'wsl': v['wsl'],
                'difference_percent': v['difference_percent'],
                'faster_platform': v['faster_platform']
            } for k, v in comparison.items()},
            'system_analysis': system_analysis
        }, f, indent=2, default=str)
    
    print(f"\nDetailed results saved to: {output_json}\n")

if __name__ == '__main__':
    main()
