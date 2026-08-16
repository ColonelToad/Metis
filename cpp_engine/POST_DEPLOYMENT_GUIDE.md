# Post-Deployment Guide — Phase 2 Week 1 on WSL2

Once `DEPLOY_TO_WSL2.ps1` completes, you'll have cpp_engine running on WSL2 native Linux.

## Immediate Validation (5 minutes)

```bash
# SSH into WSL2
wsl

# Navigate to project
cd ~/projects/metis-cpp

# Run the validation checklist (automated)
bash WSL2_VALIDATION_CHECKLIST.md  # (will be converted to .sh if needed)
```

**Expected output:**
```
=== Setup Complete ===
Phase 1 tests passed. Ready for Phase 2 implementation.
```

---

## Manual Validation (if script errors)

### 1. Verify Build Succeeded
```bash
cd ~/projects/metis-cpp
ls -lah build/
cmake --version  # Should be 3.24+
ninja --version  # Should be present
```

### 2. Run Phase 1 Tests
```bash
cd build
ctest --verbose --output-on-failure
```

**Expected:** 3 PASS (orderbook, fusion, execution_algos)

### 3. Run Phase 2 Tests
```bash
ctest -R "dpdk_ingest|sbe_parser" --verbose
```

**Expected:** 12+ PASS (SBE parser 8, DPDK ingest 4-5)

### 4. Capture Baseline Latencies
```bash
cmake --build . --target benchmark_runner --config Release
./benchmark_runner --benchmark_min_time=0.1 --benchmark_repetitions=1
```

**Record these numbers:**
- `BM_SBEParserParseTrade`: ________ ns
- `BM_DpdkIngestEngineConstruction`: ________ ns
- `BM_DpdkIngestEnginePoll`: ________ ns

---

## Troubleshooting

### "ctest: command not found"
```bash
cmake --build build --target metis-tests
cd build && ./metis-tests
```

### "benchmark_runner: command not found"
```bash
cmake --build . --target benchmark_runner --config Release
ls -lah | grep benchmark
```

### "DPDK not found"
```bash
pkg-config --cflags --libs libdpdk
# If empty, DPDK didn't install correctly:
sudo ninja -C /tmp/dpdk-build-23.11/dpdk-23.11/build install
```

### "Multicast test times out"
This is expected on WSL2. The socket-based receiver may not receive bridged multicast. 
**This does NOT block Phase 2 — skip to SBE parser tests which validate independently.**

```bash
# Test just the SBE parser (doesn't require network)
ctest -R "sbe_parser" --verbose
# Should be 8/8 PASS
```

---

## Next Steps (Week 2)

Once baseline is captured and all Phase 1 tests pass:

1. **DPDK EAL Integration** (if multicast is working)
   - Replace socket with mempool + ring buffer
   - Measure latency improvement

2. **Order Book Integration**
   - Wire SBE signals into update_quote()
   - End-to-end latency benchmark

3. **Profiling**
   - `perf record` on hot paths
   - Identify bottlenecks

4. **Native Linux Transition** (Week 4)
   - Move to Ubuntu 22.04 or CentOS 8
   - Real multicast validation

---

## Files Reference

| File | Purpose |
|------|---------|
| `WSL2_WEEK1_SETUP.sh` | Main setup script (run via DEPLOY_TO_WSL2.ps1) |
| `WEEK1_IMPLEMENTATION.md` | Detailed design walkthrough |
| `WSL2_VALIDATION_CHECKLIST.md` | Step-by-step validation checklist |
| `PHASE_2_WEEK1_COMPLETE.md` | Completion summary + roadmap |

---

## Success Criteria ✅

- [ ] All Phase 1 tests PASS on WSL2
- [ ] SBE parser tests: 8/8 PASS
- [ ] DPDK ingest tests: 4-5/5 PASS (socket-based)
- [ ] Baseline latencies recorded
- [ ] Ready to begin Week 2 DPDK EAL integration

Once all above are checked, you're ready for Week 2!

