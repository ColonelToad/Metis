# Phase 2 Setup: DPDK + SBE Parser

## Structure Created

### Headers (Interface Definitions)

1. **`include/metis/dpdk_ingest.hpp`**
   - `DpdkIngestConfig` struct (multicast address, port, ring size)
   - `DpdkIngestEngine` class (kernel-bypass UDP multicast receiver)
   - `MarketDataPacket` struct (raw packet with arrival timestamp)

2. **`include/metis/sbe_parser.hpp`**
   - `MarketDataSignal` struct (decoded market data with timestamp, symbol, trade/quote/depth)
   - `SBEParser` class (zero-copy CME MDP 3.0 SBE decoder)
   - Helpers: Trade, Quote, OrderBookDepth message parsing

3. **`include/metis/decision_layer.hpp`**
   - `RiskDecisionLayer` abstract interface (pre-trade risk checks)
   - `StubRiskDecisionLayer` (stub for Phase 2, always allows orders)

### Implementation Stubs

- `src/networking/dpdk_ingest.cpp` — EAL init, multicast socket setup (throws for now)
- `src/networking/sbe_parser.cpp` — Message parsing helpers (returns nullopt for now)
- `src/decision/decision_layer.cpp` — Placeholder for Phase 3+ FPGA/hardware integration

### Build Changes

- Updated `src/CMakeLists.txt` to include networking and decision modules
- Updated `tests/CMakeLists.txt` to link GTest::gtest and GTest::gtest_main (CMake targets)
- Made LTO optional (`-DENABLE_LTO=ON`) to work around MinGW/FetchContent GTest linking issues

## Known Issues

**Build on Windows (MinGW64) fails due to:**
- FetchContent GTest library linking issues with LTO enabled
- Likely root cause: Windows file permissions + git object caching in build/_deps

**Solution: Build on WSL2 native Linux**
- Per spike research, WSL2 is recommended for Phase 2 prototyping
- Move cpp_engine to WSL2 filesystem (/home/user/projects/metis-cpp)
- Rebuild on Linux: `cmake -DCMAKE_BUILD_TYPE=Release && ninja`
- All Phase 1 tests should pass immediately

## Next Steps (Phase 2 Implementation)

### Week 1–2 (WSL2 Prototype)

1. **DPDK Setup Spike**
   ```bash
   # WSL2: Install DPDK dependencies
   sudo apt-get install -y build-essential meson ninja-build \
     libnuma-dev pkg-config libssl-dev liburcu-dev libpcap-dev

   # Download DPDK 23.11 LTS
   wget https://fast.dpdk.org/rel/dpdk-23.11.tar.xz
   tar -xf dpdk-23.11.tar.xz && cd dpdk-23.11
   meson setup build -Dprefix=/usr/local --buildtype=release
   ninja -C build && sudo ninja -C build install
   ```

2. **Validate EAL + TAP device**
   ```bash
   # Test basic DPDK init (will use eth_tap on WSL2)
   dpdk-testpmd -l 0-1 --vdev=eth_tap0,iface=eth0
   ```

3. **Implement DpdkIngestEngine**
   - EAL initialization with fallback to --vdev=eth_tap
   - Mempool allocation (2M buffers @ 2KB)
   - Multicast socket RX queue creation

4. **Implement SBEParser**
   - Parse CME MDP 3.0 frame header
   - Decode Trade, Quote, OrderBookDepth messages
   - Zero-copy deserialization

5. **Integration Tests**
   - Mock SBE packet generator
   - Validate ingest → order book update latency
   - Benchmark with Google Benchmark

### Week 3–4 (Hardware Readiness)

1. **Native Linux Build**
   - Port to Ubuntu 22.04 LTS or CentOS 8
   - Enable DPDK physical NIC drivers (e1000, ixgbe, etc.)

2. **Multicast Validation**
   - Subscribe to CME test multicast feed (if available)
   - Measure p50/p99 ingest latency
   - Profile with perf

3. **Decision Layer Hooks**
   - Stub pre-trade risk checks
   - Prepare interface for Phase 3 FPGA integration

## References

- **DPDK 23.11 Docs:** https://doc.dpdk.org/guides-23.11/
- **CME MDP 3.0:** https://cmegroupclientsite.atlassian.net/wiki/display/EPICSANDBOX/CME+MDP+3.0+Market+Data (requires CME credentials)
- **SBE Reference:** EPAM Java handler (https://github.com/epam/java-cme-mdp3-handler)
- **WSL2 Multicast Issues:** https://github.com/microsoft/WSL/issues/12344

## Why WSL2 for Phase 2

1. ✅ DPDK TAP device works (learning curve low)
2. ✅ SBE parser is platform-agnostic (C++ source)
3. ✅ Multicast testing without real CME feed (mock packets)
4. ⚠️ Hyper-V tax on latency (~10–20µs overhead)
5. ⚠️ Multicast RX from Windows→WSL2 may drop under load

**Plan:** Spend 2–3 weeks on WSL2 for rapid SBE parser development. Migrate to native Linux by week 4 for real multicast validation and co-location readiness.
