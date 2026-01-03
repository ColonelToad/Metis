# Metis Setup Guide

## Prerequisites

### Required Software
- **Python 3.11+**: [Download](https://www.python.org/downloads/)
- **Rust 1.75+**: Install via [rustup](https://rustup.rs/)
  ```bash
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
  ```
- **Node.js 20+**: [Download](https://nodejs.org/)
- **Docker Desktop**: [Download](https://www.docker.com/products/docker-desktop/)
- **Git**: [Download](https://git-scm.com/downloads)

### Verify Installation
```bash
python --version  # Should be 3.11+
cargo --version   # Should be 1.75+
node --version    # Should be 20+
docker --version
```

---

## Step 1: Clone and Initial Setup

```bash
cd c:\Users\legot\Metis

# Copy environment template
copy .env.example .env

# Edit .env with your API keys (optional for initial testing)
notepad .env
```

---

## Step 2: Start Infrastructure (Docker)

Start TimescaleDB, Milvus, and Redis:

```bash
cd infrastructure
docker-compose up -d

# Verify containers are running
docker ps

# Check database
docker exec -it metis-timescaledb psql -U postgres -d metis -c "\dt"
```

Expected output: List of tables (market_data, climate_features, etc.)

---

## Step 3: Python Research Environment

```bash
cd ..\research

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Test installation
python -c "import torch; import pandas; print('Python setup OK')"
```

### Test Data Ingestion

```bash
# Test climate features
python features\climate_features.py

# Expected output: DataFrame with weather features
```

---

## Step 4: Rust Execution Layer

```bash
cd ..\execution

# Build all crates
cargo build --release

# Run tests
cargo test

# Expected output: All tests passing
```

### Test Order Book

```bash
cargo test --package orderbook -- --nocapture
```

Expected output: Test results showing order book operations.

---

## Step 5: RAG Pipeline Setup

```bash
cd ..\rag

# Wait for Milvus to be ready (may take 30-60 seconds)
timeout /t 30

# Index sample documents
python indexing\document_ingester.py

# Expected output: "Document ingestion complete"
```

---

## Step 6: Verify End-to-End Pipeline

### Start Rust Signal Server

```bash
cd ..\execution

# Build and run signal interface server
cargo run --package signal_interface --example server

# Expected output: "Signal server listening on 127.0.0.1:8080"
```

### Send Test Signal (in new terminal)

```bash
cd research

# Activate venv
venv\Scripts\activate

# Send test signal
python signal_client.py

# Expected output: Signal accepted with execution response
```

---

## Step 7: Run Sample Backtest

```bash
cd research

# Activate venv if not already active
venv\Scripts\activate

# Run baseline LSTM training (coming in next setup phase)
# python models\train_baseline_lstm.py
```

---

## Troubleshooting

### Docker Issues

**Problem**: Containers won't start
```bash
# Check logs
docker-compose logs timescaledb
docker-compose logs milvus

# Reset and restart
docker-compose down -v
docker-compose up -d
```

**Problem**: Port conflicts (5432 or 19530 already in use)
- Edit `docker-compose.yml` to use different ports
- Or stop conflicting services

### Python Issues

**Problem**: Package installation fails
```bash
# Update pip
python -m pip install --upgrade pip

# Install packages one by one to identify issue
pip install numpy pandas torch
```

**Problem**: Can't connect to database
- Verify Docker containers are running: `docker ps`
- Check `.env` has correct DB_HOST (should be `localhost`)
- Wait 10 seconds after `docker-compose up` for DB to initialize

### Rust Issues

**Problem**: Compilation errors
```bash
# Update Rust
rustup update

# Clean and rebuild
cargo clean
cargo build
```

**Problem**: Tests fail
- Check if port 8080 is available for signal server tests
- Some tests may require Docker databases to be running

### Milvus Issues

**Problem**: Can't connect to Milvus
```bash
# Check Milvus status
docker logs metis-milvus

# Verify Milvus is ready (may take 1-2 minutes)
curl http://localhost:9091/healthz
```

---

## Next Steps

Once setup is complete:

1. **Day 1**: Acquire CME NG tick data
   - Sign up for [Databento](https://databento.com/) free trial
   - Download 1 week of NGZ24 (Dec 2024 Natural Gas) tick data
   - Place CSV files in `data/tick_data/`

2. **Day 2**: Build Rust LOB parser
   - Implement PCAP/CSV reader in `execution/orderbook`
   - Test on sample data

3. **Day 3**: Train baseline LSTM
   - Fetch weather data via Open-Meteo
   - Train simple next-hour price prediction model
   - Establish performance baseline

See [ROADMAP.md](ROADMAP.md) for detailed 8-week plan.

---

## Verification Checklist

- [ ] Docker containers running (TimescaleDB, Milvus, Redis)
- [ ] Python environment activated with all packages installed
- [ ] Rust workspace compiles without errors
- [ ] Database schema initialized (check with `docker exec -it metis-timescaledb psql -U postgres -d metis -c "\dt"`)
- [ ] RAG documents indexed in Milvus
- [ ] Rust signal server can start on port 8080
- [ ] Python signal client can connect and send test signals
- [ ] Can fetch weather data from Open-Meteo API

---

## Useful Commands

```bash
# Start all services
cd infrastructure && docker-compose up -d

# Stop all services
cd infrastructure && docker-compose down

# View logs
docker-compose logs -f timescaledb
docker-compose logs -f milvus

# Activate Python environment
cd research && venv\Scripts\activate

# Run Rust tests
cd execution && cargo test

# Build Rust release
cd execution && cargo build --release

# Format Rust code
cd execution && cargo fmt

# Check Rust code
cd execution && cargo clippy
```

---

## Resources

- **CME Natural Gas Data**: https://www.cmegroup.com/market-data/datamine.html
- **Databento**: https://databento.com/
- **Open-Meteo Weather API**: https://open-meteo.com/
- **GridStatus.io**: https://www.gridstatus.io/
- **Congress.gov API**: https://api.congress.gov/
- **EIA Natural Gas**: https://www.eia.gov/naturalgas/
- **FRED API**: https://fred.stlouisfed.org/docs/api/

---

## Contact & Support

For issues or questions:
1. Check troubleshooting section above
2. Review GitHub issues (if repository is public)
3. Consult project documentation in `docs/`
