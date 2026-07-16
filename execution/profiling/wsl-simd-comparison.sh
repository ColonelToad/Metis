#!/usr/bin/env bash
#
# Run 3 isolated SIMD benchmark trials on WSL with system state monitoring
# Usage: bash wsl-simd-comparison.sh [--trials N] [--skip-cleanup]

set +e  # Don't exit on errors, we want to continue monitoring

# Parse arguments
TRIALS=3
SKIP_CLEANUP=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --trials) TRIALS="$2"; shift 2 ;;
        --skip-cleanup) SKIP_CLEANUP=true; shift ;;
        *) echo "Unknown option: $1"; shift ;;
    esac
done

# Setup paths
PROJECT_ROOT="/mnt/c/Users/legot/Metis"
CORE_DIR="$PROJECT_ROOT/metis-core"
PROF_DIR="$PROJECT_ROOT/profiling"
TS=$(date +%Y-%m-%d_%H%M%S)
TRIAL_DIR="$PROF_DIR/simd_trials_wsl_$TS"
METRICS_FILE="$TRIAL_DIR/system_metrics.csv"
BENCHMARK_FILE="$TRIAL_DIR/benchmark_results.csv"
SUMMARY_FILE="$TRIAL_DIR/summary.txt"

# Create output directory
mkdir -p "$TRIAL_DIR"

LOG_FILE="$TRIAL_DIR/run.log"

write_log() {
    local msg="$1"
    local ts=$(date '+%H:%M:%S')
    echo "[$ts] $msg" | tee -a "$LOG_FILE"
}

get_system_metrics() {
    local trial=$1
    
    # CPU info
    local cpu_model=$(grep -m1 "model name" /proc/cpuinfo | cut -d: -f2 | xargs)
    local cpu_cores=$(grep -c "^processor" /proc/cpuinfo)
    
    # Memory info
    local mem_info=$(free -g | awk 'NR==2')
    local mem_total=$(echo $mem_info | awk '{print $2}')
    local mem_used=$(echo $mem_info | awk '{print $3}')
    local mem_free=$(echo $mem_info | awk '{print $4}')
    local mem_percent=$(awk "BEGIN {printf \"%.1f\", ($mem_used/$mem_total)*100}")
    
    # Load average
    local load=$(cat /proc/loadavg | awk '{print $1}')
    
    # Process count
    local proc_count=$(ps aux | wc -l)
    
    echo "CPU_Model:$cpu_model|Cores:$cpu_cores|Mem_Total:${mem_total}G|Mem_Used:${mem_used}G|Mem_Free:${mem_free}G|Mem_Percent:${mem_percent}%|Load:$load|Procs:$proc_count"
}

get_cpu_frequency() {
    # Try to read current CPU frequency from /proc/cpuinfo or scaling_cur_freq
    if [ -f /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq ]; then
        local freq_khz=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq)
        echo $((freq_khz / 1000))  # Convert to MHz
    elif grep -q "cpu MHz" /proc/cpuinfo; then
        grep "cpu MHz" /proc/cpuinfo | head -1 | cut -d: -f2 | xargs | cut -d. -f1
    else
        echo "unknown"
    fi
}

monitor_system() {
    local trial=$1
    local duration=${2:-120}  # Default 120 seconds
    
    write_log "Starting system monitoring for Trial $trial (duration: ${duration}s)"
    
    # Add header if file doesn't exist
    if [ ! -f "$METRICS_FILE" ]; then
        echo "Timestamp,Trial,Elapsed_Sec,CPU_MHz,Memory_Used_GB,Memory_Percent,Process_Count,Load_Avg" > "$METRICS_FILE"
    fi
    
    local start_time=$(date +%s)
    local elapsed=0
    
    while [ $elapsed -lt $duration ]; do
        local now=$(date +%s)
        elapsed=$((now - start_time))
        
        local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
        local cpu_mhz=$(get_cpu_frequency)
        local mem_info=$(free -g | awk 'NR==2 {print $3, ($3/$2)*100}')
        local mem_used=$(echo $mem_info | awk '{print $1}')
        local mem_percent=$(echo $mem_info | awk '{printf "%.1f", $2}')
        local proc_count=$(ps aux | wc -l)
        local load=$(cat /proc/loadavg | awk '{print $1}')
        
        echo "$timestamp,$trial,$elapsed,$cpu_mhz,$mem_used,$mem_percent,$proc_count,$load" >> "$METRICS_FILE"
        
        sleep 0.5
    done
    
    write_log "System monitoring complete for Trial $trial"
}

parse_benchmark_output() {
    local output_file=$1
    local trial=$2
    
    # Extract benchmark names and timings
    # Pattern: time:   [156.58 ns 160.55 ns 164.79 ns]
    
    awk -v trial=$trial '
    /^simd_normalization\/(.*?)$/ || /^euclidean_distance\/(.*?)$/ {
        match($0, /^([a-z_]+)\/([a-z_0-9]+)/, arr)
        if (arr[2]) {
            benchmark = arr[2]
        }
    }
    /time:.*\[.*ns.*ns.*ns\]/ && benchmark {
        gsub(/[^0-9. ]/, "")
        split($0, times)
        if (times[1] && times[2] && times[3]) {
            printf "%d,%s,%.2f,%.2f,%.2f\n", trial, benchmark, times[1], times[2], times[3]
            benchmark = ""
        }
    }
    ' "$output_file"
}

run_benchmark_trial() {
    local trial=$1
    
    write_log "========== TRIAL $trial =========="
    
    # Get pre-trial metrics
    local pre_metrics=$(get_system_metrics $trial)
    write_log "Pre-trial state: $pre_metrics"
    
    # Clear Criterion cache if not first trial
    if [ $trial -gt 1 ] && [ "$SKIP_CLEANUP" = false ]; then
        write_log "Clearing Criterion cache..."
        rm -rf "$CORE_DIR/target/criterion"
    fi
    
    # Start background monitoring (estimated 60-90 seconds for benchmark)
    monitor_system $trial 120 &
    MONITOR_PID=$!
    
    # Run benchmark
    write_log "Running benchmark..."
    cd "$CORE_DIR"
    cargo bench --bench simd_vectorization 2>&1 | tee "$TRIAL_DIR/trial_${trial}_raw.txt"
    BENCH_EXIT=$?
    
    # Wait for monitoring to finish
    wait $MONITOR_PID 2>/dev/null
    
    # Extract results
    write_log "Parsing benchmark results..."
    parse_benchmark_output "$TRIAL_DIR/trial_${trial}_raw.txt" $trial >> "$BENCHMARK_FILE"
    
    # Get post-trial metrics
    local post_metrics=$(get_system_metrics $trial)
    write_log "Post-trial state: $post_metrics"
    write_log ""
}

# Main execution
{
    write_log "========== SIMD Benchmark Comparison - WSL =========="
    write_log "Project: $PROJECT_ROOT"
    write_log "Trials: $TRIALS"
    write_log "Output: $TRIAL_DIR"
    write_log ""
    
    # Initialize results file header
    echo "Trial,Benchmark,Time_NS,Lower_NS,Upper_NS" > "$BENCHMARK_FILE"
    
    # Get baseline system info
    write_log "Baseline System State:" 
    local baseline=$(get_system_metrics "BASELINE")
    write_log "  $baseline"
    write_log ""
    
    # Verify we're in WSL
    if grep -qi "microsoft" /proc/version; then
        write_log "Confirmed: Running in WSL"
    else
        write_log "WARNING: Not detected as WSL environment"
    fi
    write_log ""
    
    # Run trials
    for ((trial=1; trial<=TRIALS; trial++)); do
        run_benchmark_trial $trial
    done
    
    # Summary
    write_log "========== RESULTS SUMMARY =========="
    write_log "Benchmark results: $BENCHMARK_FILE"
    write_log "System metrics: $METRICS_FILE"
    write_log "Raw outputs: $TRIAL_DIR/trial_*_raw.txt"
    write_log ""
    write_log "Next: Compare Windows and WSL results using:"
    write_log "  python3 $PROF_DIR/compare_simd_results.py"
    
} | tee -a "$LOG_FILE"
