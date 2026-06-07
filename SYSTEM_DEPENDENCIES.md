# Metis System Library Dependency Document

**Purpose**: Define all system-level dependencies required to build and run Metis across Windows and WSL environments.

**Last Updated**: [DATE]
**Status**: [IN PROGRESS / DRAFT / COMPLETE]

---

## Quick Setup Checklist

### Windows (PowerShell - Run as Admin)

```powershell
# Install Rust
winget install Rustlang.Rust.MSVC

# Install build tools
winget install CMake.CMake
winget install Microsoft.VisualStudio.2022.BuildTools

# Install Node.js
winget install OpenJS.NodeJS

# Install Python
winget install Python.Python.3.11

# Verify
rustc --version
cargo --version
python --version
node --version
```

### WSL (bash)

```bash
# Update package lists
sudo apt update

# Install build essentials
sudo apt install -y build-essential cmake pkg-config

# Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Install Node.js
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Install Python
sudo apt install -y python3 python3-pip python3-venv

# Verify
rustc --version
cargo --version
python3 --version
node --version
```

---

## Dependency Matrix

| Component | Windows | WSL | Required | Optional | Version | Purpose |
|-----------|---------|-----|----------|----------|---------|---------|
| **Rust** | ✅ | ✅ | YES | - | 1.70+ | Core language |
| **Cargo** | ✅ | ✅ | YES | - | latest | Package manager |
| **MSVC** | ✅ | - | YES (Windows native) | - | 2022+ | C++ compiler for Windows |
| **GCC/G++** | - | ✅ | YES (WSL native) | - | 11+ | C++ compiler for Linux |
| **CMake** | ✅ | ✅ | YES | - | 3.20+ | Build system |
| **pkg-config** | ⚠️ (vcpkg) | ✅ | YES | - | latest | Dependency resolver |
| **Python3** | ✅ | ✅ | YES | - | 3.9+ | Data pipeline, scripts |
| **pip3** | ✅ | ✅ | YES | - | latest | Python packages |
| **Node.js** | ✅ | ✅ | YES | - | 18+ | Frontend build |
| **npm** | ✅ | ✅ | YES | - | latest | JS packages |
| **Git** | ✅ | ✅ | YES | - | latest | Version control |
| **OpenSSL** | ✅ | ✅ | YES | - | 3.0+ | TLS/crypto for R2 client |
| **libssl-dev** | - | ✅ | YES (WSL) | - | latest | SSL development headers |
| **SQLite** | (bundled) | (bundled) | NO | - | 3.36+ | Data cache backend |

---

## Detailed Dependencies by Subsystem

### Core: metis-core (Rust)

**Compilation Requirements:**

- **Rust toolchain**: 1.70+ (stable)
  - Required for: SIMD intrinsics, async/await, macro system
  - Installed via: `rustup`
  - Note: Requires `.cargo/config.toml` with `target-feature=+avx2,+fma` for SIMD performance

- **MSVC (Windows) / GCC (WSL)**
  - Windows: MSVC 2022 (included with Visual Studio Build Tools)
    - Used for: C++ interop, linking against Windows system libraries
  - WSL: GCC 11+ (apt: build-essential)
    - Used for: Native Linux compilation

- **CMake**: 3.20+
  - Used for: Configuring external C++ dependencies
  - Installed via: `winget` (Windows), `apt` (WSL)

- **pkg-config**
  - Windows: Provided by vcpkg
  - WSL: `sudo apt install pkg-config`
  - Used for: Resolving library paths during compilation

**Runtime Requirements:**

- **PyO3 runtime** (pyo3 v0.23)
  - Used for: Python bindings
  - Requires: Python 3.9+, proper header paths
  - Location: `/usr/include/python3.x` (WSL), `C:\Program Files\Python\include` (Windows)

### Data: research/ (Python)

**Compilation/Installation:**

- **Python 3.9+**
  - Windows: `winget install Python.Python.3.11`
  - WSL: `sudo apt install python3 python3-pip python3-dev`

- **pip packages** (from requirements.txt):
  - NumPy: Scientific computing
  - Pandas: Data manipulation
  - Scikit-learn: ML models
  - PyArrow: Data serialization
  - Boto3: AWS/R2 client (requires OpenSSL)
  - And others (see [research/requirements.txt](research/requirements.txt))

**Runtime Requirements:**

- **OpenSSL 3.0+**
  - Windows: Bundled with Python
  - WSL: `libssl-dev` (development headers)
  - Used for: TLS connections to R2, secure HTTP

### Frontend: metis/ (Node.js + TypeScript)

**Compilation Requirements:**

- **Node.js 18+**
  - Windows: `winget install OpenJS.NodeJS`
  - WSL: See setup section
  - Used for: React build system, Vite transpilation

- **npm**
  - Included with Node.js
  - Used for: JavaScript dependency management

**Runtime Requirements:**

- **Tauri (Rust + Electron equivalent)**
  - Requires: Rust, system webview libraries
  - Windows: WebView2 (built-in on Windows 11)
  - WSL: Not directly (builds Windows binary)

### Execution: execution/ (Rust + Binary Trading)

**Compilation Requirements:**

- Same as metis-core (Rust, MSVC/GCC)

**Runtime Requirements:**

- **System-level concurrency** (no external lib, uses OS primitives)
- **Memory mapping** for orderbook (platform-specific)
  - Windows: VirtualAlloc API
  - WSL/Linux: mmap syscall

### RAG: rag/ (Rust + Python bindings)

**Compilation Requirements:**

- Rust + MSVC/GCC (same as core)
- C++ (for embedded vector search)

**Runtime Requirements:**

- **SQLite**: Model/embedding storage
  - Windows: Bundled via rusqlite crate
  - WSL: `libsqlite3-dev` (if using system SQLite)

---

## Platform-Specific Notes

### Windows

**Power Management Issue** (June 2026):
- CPU frequency capped at 1700 MHz (BIOS/OS default)
- Affects: SIMD benchmark performance (-58% vs WSL)
- Status: Under investigation

**Recommended Configuration:**
- Power Plan: "High Performance"
- BIOS: Check CPU power limits (PL1/PL2)
- Visual Studio Build Tools: Install full C++ workload

### WSL

**Advantages:**
- Default frequency: 2688 MHz (full hardware capability)
- Linux kernel behavior matches production environments
- Better isolation for benchmarking

**Requirements:**
- WSL2 (not WSL1) for performance
- `.wslconfig` for memory/CPU allocation
- `/mnt/c/Users/...` for accessing Windows files

**Known Issues:**
- None currently documented

---

## Validation Script

After installing dependencies, run:

```powershell
# Windows
.\audit_windows_dependencies.ps1

# WSL
bash audit_wsl_dependencies.sh
```

These scripts verify all required dependencies are installed and report version information.

---

## Build Verification

### Windows

```powershell
cd metis-core
cargo build --release
cargo test --release
cargo bench --bench simd_vectorization
```

### WSL

```bash
cd /mnt/c/Users/legot/Metis/metis-core
cargo build --release
cargo test --release
cargo bench --bench simd_vectorization
```

**Expected results:**
- Build completes in < 2 minutes
- Tests pass with 0 failures
- SIMD benchmarks show > 5x speedup

---

## Dependency Update Policy

**Checked**: [Monthly / As-needed]
**Last Checked**: [DATE]

### To Update:

1. Run audit scripts to check current versions
2. For Rust: `rustup update`
3. For Python: `pip install --upgrade -r requirements.txt`
4. For Node: `npm update -g`
5. For system: `apt update && apt upgrade` (WSL), `winget upgrade` (Windows)
6. Re-run build verification
7. Update this document with new versions

---

## Troubleshooting

**"Cargo: command not found"**
- Windows: Add `C:\Users\<username>\.cargo\bin` to PATH
- WSL: Source `$HOME/.cargo/env`

**"MSVC not found" (Windows)**
- Install Visual Studio Build Tools with C++ workload
- Or set `CARGO_CFG_TARGET_FEATURE` manually

**"Python.h: No such file"**
- Windows: `pip install --upgrade pip` (installs headers)
- WSL: `sudo apt install python3-dev`

**SIMD not compiling (0.34x speedup)**
- Verify `.cargo/config.toml` has `target-feature=+avx2,+fma`
- Run: `cargo clean && cargo build --release`

---

## Future Work

- [ ] Automate dependency installation scripts
- [ ] Add Docker/container setup for consistent environments
- [ ] Document macOS setup (if adding Apple Silicon target)
- [ ] Track minimum vs. recommended versions separately
- [ ] Add dependency deprecation timeline

