# Manual WSL2 Setup — Phase 2 Week 1

If `DEPLOY_TO_WSL2.ps1` can't run (WSL2 not available in this environment), follow these manual steps.

## Step 1: Start WSL2 (Windows PowerShell)

```powershell
# Start WSL2 in default distribution
wsl

# Or, to list available distros:
wsl --list --verbose

# To use a specific distro:
wsl -d Ubuntu
```

## Step 2: Copy cpp_engine to WSL2 (Inside WSL2)

```bash
# Inside WSL2 terminal
mkdir -p ~/projects
cp -r /mnt/c/Users/legot/Metis/cpp_engine ~/projects/metis-cpp
cd ~/projects/metis-cpp

# Verify copy succeeded
ls -lah
git status  # Should show no uncommitted changes
```

## Step 3: Run Setup Script (Inside WSL2)

```bash
cd ~/projects/metis-cpp
bash WSL2_WEEK1_SETUP.sh
```

**Expected output:**
```
=== Phase 2 Week 1: WSL2 Setup ===
[1/6] Installing system dependencies...
[2/6] Setting up project directory...
[3/6] Installing DPDK 23.11 LTS...
   Building DPDK (this may take 5-10 minutes)...
[4/6] Configuring pkg-config...
[5/6] Building Phase 2 infrastructure...
[6/6] Running Phase 1 tests to validate build...

=== Setup Complete ===
Phase 1 tests passed. Ready for Phase 2 implementation.
```

**If setup script hangs or errors:**

### Option A: Run steps manually

```bash
# 1. System dependencies
sudo apt-get update
sudo apt-get install -y build-essential meson ninja-build pkg-config \
    libnuma-dev libssl-dev liburcu-dev libpcap-dev cmake git python3-pip \
    linux-headers-$(uname -r)

# 2. DPDK 23.11 LTS
cd /tmp
wget https://fast.dpdk.org/rel/dpdk-23.11.tar.xz
tar -xf dpdk-23.11.tar.xz && cd dpdk-23.11
meson setup build -Dprefix=/usr/local --buildtype=release -Dtests=false -Ddocs=false
ninja -C build
sudo ninja -C build install

# 3. pkg-config path
export PKG_CONFIG_PATH=/usr/local/lib/pkgconfig:$PKG_CONFIG_PATH
echo "export PKG_CONFIG_PATH=/usr/local/lib/pkgconfig:\$PKG_CONFIG_PATH" >> ~/.bashrc

# 4. Build cpp_engine
cd ~/projects/metis-cpp
cmake -B build -S . -DCMAKE_BUILD_TYPE=Release -DCMAKE_GENERATOR=Ninja
cmake --build build --config Release

# 5. Run Phase 1 tests
cd build && ctest --verbose
```

### Option B: Run specific failing step again

If step N fails, rerun that step:

```bash
# Step 3: DPDK installation
DPDK_BUILD_DIR="/tmp/dpdk-build-23.11"
mkdir -p "$DPDK_BUILD_DIR"
cd "$DPDK_BUILD_DIR"
wget -q "https://fast.dpdk.org/rel/dpdk-23.11.tar.xz"
tar -xf "dpdk-23.11.tar.xz"
cd "dpdk-23.11"
meson setup build -Dprefix=/usr/local --buildtype=release -Dtests=false -Ddocs=false
ninja -C build
sudo ninja -C build install

# Step 4: pkg-config
export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:$PKG_CONFIG_PATH"

# Step 5: CMake build
cd ~/projects/metis-cpp
cmake -B build -S . -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release

# Step 6: Tests
cd build && ctest --verbose
```

## Step 4: Validate Phase 1 Tests

```bash
cd ~/projects/metis-cpp/build
ctest --verbose --output-on-failure
```

**Expected output:**
```
Test project /home/legot/projects/metis-cpp/build
    Start 1: metis_unit_tests
1/1 Test #1: metis_unit_tests ...................... PASSED
100% tests passed, 0 tests failed out of 1
```

If tests fail, check:
- GTest was found/built: `ls -lah /usr/local/lib/libgtest*`
- CMake used correct compiler: `cmake -B build -S . --debug-output | grep -i compiler`

## Step 5: Capture Baseline Latencies

```bash
cd ~/projects/metis-cpp/build
cmake --build . --target benchmark_runner --config Release
./benchmark_runner --benchmark_min_time=0.1 --benchmark_repetitions=1
```

**Record the latencies printed:**
```
BM_SBEParserParseTrade                   __ ns/iter
BM_DpdkIngestEngineConstruction          __ ns/iter
BM_DpdkIngestEnginePoll                  __ ns/iter
```

## Step 6: Verify Files

```bash
# Confirm all expected files are present
cd ~/projects/metis-cpp
ls -lah include/metis/dpdk_ingest.hpp          # ✓ Should exist
ls -lah include/metis/sbe_parser.hpp           # ✓ Should exist
ls -lah include/metis/decision_layer.hpp       # ✓ Should exist
ls -lah src/networking/dpdk_ingest.cpp         # ✓ Should exist
ls -lah src/networking/sbe_parser.cpp          # ✓ Should exist
ls -lah tests/dpdk_ingest_test.cpp             # ✓ Should exist
ls -lah tests/sbe_parser_test.cpp              # ✓ Should exist
ls -lah benchmarks/ingest_latency_benchmark.cpp # ✓ Should exist

# Check git status (should be clean)
git status
# Output should be: "working tree clean"
```

## Troubleshooting

### "sudo: command not found"
You're not running as root. Some systems don't have sudo. Try:
```bash
su -
# Then run commands without sudo
apt-get update
apt-get install -y ...
```

### "pkg-config: command not found"
Install it:
```bash
sudo apt-get install -y pkg-config
```

### "CMake not found"
```bash
sudo apt-get install -y cmake
cmake --version  # Should be 3.24+
```

### "Ninja not found"
```bash
sudo apt-get install -y ninja-build
ninja --version
```

### "DPDK build fails"
Check for missing dependencies:
```bash
sudo apt-get install -y meson libnuma-dev libssl-dev liburcu-dev libpcap-dev
```

Then retry:
```bash
cd /tmp/dpdk-23.11
meson setup build -Dprefix=/usr/local --buildtype=release
ninja -C build
sudo ninja -C build install
```

### "GTest linking fails"
Try installing system GTest:
```bash
sudo apt-get install -y libgtest-dev
cd /usr/src/gtest
sudo cmake .
sudo make
sudo cp lib/*.a /usr/lib/x86_64-linux-gnu/
```

Then rebuild:
```bash
cd ~/projects/metis-cpp
rm -rf build
cmake -B build -S .
cmake --build build --config Release
```

### "All tests pass but latencies are >100µs"
This is expected on WSL2 due to Hyper-V overhead. Record them and move forward to Week 2.

```bash
echo "WSL2 baseline (with Hyper-V tax):" > latencies.txt
./build/benchmark_runner --benchmark_min_time=0.1 --benchmark_repetitions=5 >> latencies.txt
cat latencies.txt
```

## Next Steps (Week 2)

Once Phase 1 tests pass and baselines are recorded:

1. **Follow WSL2_VALIDATION_CHECKLIST.md** for final validation
2. **Update memory** with baseline latencies
3. **Begin Week 2**: DPDK EAL integration (replace socket with mempool)

---

## Quick Reference

| Command | Purpose |
|---------|---------|
| `ctest --verbose` | Run all tests |
| `ctest -R sbe_parser` | Run only SBE parser tests |
| `ctest -R dpdk_ingest` | Run only DPDK ingest tests |
| `cmake --build build --target benchmark_runner` | Build benchmarks |
| `./build/benchmark_runner` | Run latency benchmarks |
| `git status` | Check for uncommitted changes |

---

## Success Criteria ✅

- [ ] DPDK 23.11 LTS installed (`pkg-config --cflags --libs libdpdk` returns non-empty)
- [ ] Phase 1 tests PASS (3/3)
- [ ] SBE parser tests PASS (8/8)
- [ ] DPDK ingest tests PASS (4-5/5)
- [ ] Baseline latencies recorded
- [ ] `git status` shows clean working tree

Once all are checked, move to Week 2!

