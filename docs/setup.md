# Setup Guide

This guide covers everything required to build and run Metis from a fresh clone. The system has three independent build targets — Python, Rust, and Node.js — each with its own dependency chain. You do not need all three to get started; the Python pipeline runs standalone.

---

## System Requirements

| Tool | Version | Required for |
|------|---------|--------------|
| Python | 3.11+ | Research pipeline, RAG |
| Rust | 1.75+ (stable) | Execution engine, metis-core, Tauri backend |
| Node.js | 20+ | Tauri frontend |
| CMake | 3.20+ | C++ interop in Rust builds |
| Git | any | Version control |

---

## Windows Setup

Run the following in PowerShell as Administrator:

```powershell
# Core toolchain
winget install Rustlang.Rust.MSVC
winget install CMake.CMake
winget install Microsoft.VisualStudio.2022.BuildTools  # select "Desktop development with C++"
winget install OpenJS.NodeJS
winget install Python.Python.3.11

# Verify
rustc --version    # 1.75+
cargo --version
python --version   # 3.11+
node --version     # 20+
cmake --version    # 3.20+
```

**Visual Studio Build Tools**: when the installer opens, select the **"Desktop development with C++"** workload. The C++ compiler (MSVC) is required by several Rust crates.

**Performance note**: Windows may cap CPU frequency under default power plans, which reduces SIMD benchmark scores significantly. Set your power plan to **High Performance** and verify BIOS power limits (PL1/PL2) if running benchmarks.

---

## WSL Setup

```bash
# Build essentials
sudo apt update
sudo apt install -y build-essential cmake pkg-config libssl-dev python3-dev libsqlite3-dev

# Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"

# Node.js 20
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Python
sudo apt install -y python3.11 python3.11-venv python3-pip

# Tauri system dependencies (only needed for building the desktop app)
sudo apt install -y \
  libwebkit2gtk-4.1-dev \
  libxdo-dev \
  libayatana-appindicator3-dev \
  librsvg2-dev
```

WSL2 is required (not WSL1). For benchmarking, WSL2 runs at full CPU frequency and produces more representative results than Windows native.

---

## Environment Configuration

Copy the example env file and fill in your API keys:

```bash
cp .env.example .env
```

Required keys for the full data pipeline:

| Variable | Source | Used by |
|----------|--------|---------|
| `EIA_API_KEY` | [eia.gov/opendata](https://www.eia.gov/opendata/) | EIA storage reports |
| `FRED_API_KEY` | [fred.stlouisfed.org/docs/api](https://fred.stlouisfed.org/docs/api/api_key.html) | FRED macro series |
| `DATABENTO_API_KEY` | [databento.com](https://databento.com) | CME futures tick data |
| `CONGRESS_API_KEY` | [api.congress.gov](https://api.congress.gov) | Climate legislation |
| `FINNHUB_API_KEY` | [finnhub.io](https://finnhub.io) | Market data fallback |
| `OPENMETEO_*` | free, no key needed | Weather data |
| `R2_ACCESS_KEY_ID` | Cloudflare dashboard | R2 cloud backup |
| `R2_SECRET_ACCESS_KEY` | Cloudflare dashboard | R2 cloud backup |
| `R2_ENDPOINT_URL` | Cloudflare dashboard | R2 cloud backup |
| `R2_BUCKET_NAME` | Cloudflare dashboard | R2 cloud backup |

The pipeline will run with partial keys — ingesters that cannot authenticate will skip and log a warning rather than halt the pipeline.

---

## Python Environment

```bash
cd research
pip install -r requirements.txt
```

**Key packages installed:**

| Category | Packages |
|----------|---------|
| ML | torch, scikit-learn, xgboost, statsmodels |
| Data | numpy, pandas, pyarrow, duckdb |
| APIs | requests, aiohttp, fredapi, finnhub-python, openmeteo-requests |
| RAG / LLM | sentence-transformers, lancedb, openai, anthropic, langchain |
| Storage | sqlalchemy, boto3 |
| Testing | pytest, pytest-asyncio |
| Utilities | python-dotenv, loguru, pydantic, tqdm |

> **Note**: `requirements.txt` currently lists `chromadb` as a dependency. The project uses LanceDB as the vector store; `chromadb` is not required and can be omitted if you want a lighter install.

**Verify the install:**

```bash
cd ..   # back to repo root
python -c "from research.metrics import MetricsCollector; print('OK')"
python research/ops/ingest_wrapper.py --frequency daily
```

---

## Rust: Execution Workspace

The `execution/` directory is a Cargo workspace containing the order book simulator, TWAP/VWAP algorithms, FIX protocol client, signal interface, and AIS vessel tracking.

```bash
cd execution
cargo build --release
cargo test
```

**System deps required** (WSL/Linux):
```bash
sudo apt install -y pkg-config libssl-dev
```

The release profile uses `opt-level=3`, `lto="fat"`, `codegen-units=1`. Build times are longer than debug; expect 2–4 minutes on first build.

---

## Rust: metis-core (PyO3 Library)

`metis-core` is the Python/Rust bridge — it compiles to a native extension module (`.pyd` on Windows, `.so` on Linux) that Python imports directly.

```bash
cd metis-core
cargo build --release
```

**System deps required** (WSL/Linux):
```bash
sudo apt install -y python3-dev
```

**Windows**: Python headers are included automatically when Python is installed via the official installer or winget.

**Verify SIMD is active** (expects > 5× speedup):
```bash
cargo bench --bench simd_vectorization
```

If the speedup is < 5×, verify `.cargo/config.toml` includes:
```toml
[build]
rustflags = ["-C", "target-feature=+avx2,+fma"]
```

---

## Tauri Desktop App

```bash
cd metis
npm install
npm run tauri:dev    # development mode with hot reload
npm run tauri:build  # production binary
```

**Additional WSL/Linux deps** (already listed in WSL setup above):
```bash
sudo apt install -y libwebkit2gtk-4.1-dev libxdo-dev libayatana-appindicator3-dev librsvg2-dev
```

**Windows**: WebView2 is built into Windows 11. On Windows 10, it installs automatically via the Tauri bootstrapper.

---

## Troubleshooting

**`cargo: command not found`**
- Windows: add `%USERPROFILE%\.cargo\bin` to your PATH and restart the terminal
- WSL: run `source "$HOME/.cargo/env"` or add it to `.bashrc`

**`MSVC not found` on Windows**
- Open Visual Studio Installer → modify your Build Tools installation → ensure the **"Desktop development with C++"** workload is checked

**`Python.h: No such file or directory`**
- WSL: `sudo apt install python3-dev`
- Windows: reinstall Python from python.org using the official installer (not the Store version)

**`error: failed to run custom build command for openssl-sys`**
- WSL: `sudo apt install pkg-config libssl-dev`
- Windows: OpenSSL is typically bundled; if not, install via `vcpkg install openssl:x64-windows`

**SIMD speedup below 5×**
1. Confirm you built with `--release`
2. Check `.cargo/config.toml` for `target-feature=+avx2,+fma`
3. On Windows, check CPU frequency — default power plans cap frequency and suppress SIMD gains
4. Run `cargo clean && cargo build --release` to rule out stale artifacts
