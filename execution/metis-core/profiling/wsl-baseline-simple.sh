#!/usr/bin/env bash
#
# WSL Hardware Profiling - Simplified
#

set +e # Continue on errors

REPO="/mnt/c/Users/legot/Metis"
CORE_DIR="$REPO/metis-core"
PROF_DIR="$REPO/profiling"
TS=$(date +%Y-%m-%d_%H%M%S)
LOG="$PROF_DIR/wsl_profiling_${TS}.log"

echo "====== Metis Hardware Profiling (WSL) ======" | tee -a "$LOG"
echo "Timestamp: $TS" | tee -a "$LOG"
echo "Output: $PROF_DIR" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# Build
echo "[BUILD] Compiling metis-core..." | tee -a "$LOG"
cd "$CORE_DIR"
cargo build --release 2>&1 | tail -5 | tee -a "$LOG"
echo "" | tee -a "$LOG"

# Benchmarks
echo "[SIMD] Running SIMD vectorization benchmark..." | tee -a "$LOG"
cargo bench --bench simd_vectorization 2>&1 | tee "$PROF_DIR/wsl_simd_${TS}.txt" | tail -10 | tee -a "$LOG"
echo "" | tee -a "$LOG"

echo "[LOCKFREE] Running lock-free fusion benchmark..." | tee -a "$LOG"
cargo bench --bench lockfree_fusion 2>&1 | tee "$PROF_DIR/wsl_lockfree_${TS}.txt" | tail -10 | tee -a "$LOG"
echo "" | tee -a "$LOG"

echo "[BRIDGE] Running FFI bridge latency benchmark..." | tee -a "$LOG"
cargo bench --bench bridge_latency 2>&1 | tee "$PROF_DIR/wsl_bridge_${TS}.txt" | tail -10 | tee -a "$LOG"
echo "" | tee -a "$LOG"

# Tests
echo "[TEST] Running full test suite..." | tee -a "$LOG"
cargo test --release 2>&1 | tee "$PROF_DIR/wsl_tests_${TS}.log" | tail -20 | tee -a "$LOG"
echo "" | tee -a "$LOG"

# Summary
echo "====== PROFILING COMPLETE ======" | tee -a "$LOG"
echo "Output files:" | tee -a "$LOG"
ls -lh "$PROF_DIR"/wsl_*_${TS}.* 2>/dev/null | awk '{print "  " $9}' | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "Comparing with Windows results..." | tee -a "$LOG"
echo "Next step: Analyze cross-platform differences" | tee -a "$LOG"
