# Metis: HFT-Enhanced Climate Trading System

## Executive Summary
Metis is a production-oriented quantitative trading system that combines climate ML, policy analysis, and high-frequency trading infrastructure to demonstrate microstructure-aware execution in energy markets.

## Architecture Overview

### Three-Layer Hybrid System
1. **Research & Signal Generation (Python)**: Climate ML + Policy RAG → Trading signals
2. **Market Microstructure Engine (Rust + C++)**: Order book simulation + FIX protocol + Execution algorithms
3. **Visualization & Explanation UI (Tauri + React)**: Unified dashboard with LLM explanations

## Tech Stack
- **Python 3.11+**: ML research, feature engineering, backtesting
- **Rust 1.75+**: Low-latency execution engine, order book simulator, FIX client
- **Node.js 20+**: React frontend tooling
- **Tauri 2.0**: Desktop application framework
- **TimescaleDB**: Time-series database for market data
- **PostgreSQL 15**: Relational data storage
- **Vector DB**: Milvus or Weaviate for RAG

## Project Structure
```
metis/
├── research/              # Python: ML models and backtesting
│   ├── data_ingest/       # API clients for 10+ data sources
│   ├── features/          # Climate/policy feature engineering
│   ├── models/            # LSTM hybrid, baselines
│   └── backtest/          # Transaction cost simulator
├── execution/             # Rust: Microstructure engine
│   ├── orderbook/         # LOB simulator + PCAP parser
│   ├── execution_algos/   # TWAP/VWAP implementations
│   ├── fix_client/        # FIX session handler
│   └── signal_interface/  # Python → Rust bridge
├── rag/                   # LLM explanation pipeline
│   ├── indexing/          # Vector DB setup + doc ingestion
│   ├── retrieval/         # Semantic search
│   └── generation/        # LLM orchestration
├── ui/                    # Tauri + React frontend
│   ├── src-tauri/         # Rust backend
│   └── src/               # React components
└── infrastructure/        # Docker, DB schemas, deployment
```

## Quick Start

### Prerequisites
- Python 3.11+
- Rust 1.75+ (install via rustup)
- Node.js 20+
- Docker & Docker Compose
- Git

### Initial Setup (First 3 Days)

#### Day 1: Data Infrastructure
```bash
# Start databases
cd infrastructure
docker-compose up -d

# Install Python dependencies
cd ../research
pip install -r requirements.txt

# Test data ingestion
python data_ingest/test_connection.py
```

#### Day 2: Rust Order Book Parser
```bash
cd execution
cargo build --release
cargo test

# Run LOB parser on sample data
cargo run --bin lob_parser -- --input data/sample_ticks.csv
```

#### Day 3: Baseline ML Model
```bash
cd research/models
python train_baseline_lstm.py --data-source open-meteo
```

## Target Instrument
**CME Henry Hub Natural Gas (NG) Futures**
- High weather correlation
- Active HFT participation
- Accessible historical tick data via CME DataMine/Databento

## Performance Targets
- Signal-to-execution latency: <100ms
- Order book processing: <10μs per event
- Backtest throughput: 1M ticks/second
- RAG retrieval: <2s per query

## Success Criteria
- [ ] Backtest Sharpe >1.0 on NG futures with climate features
- [ ] Rust execution layer <5% TWAP tracking error
- [ ] RAG retrieval 90%+ accuracy on signal explanations
- [ ] Full UI with synchronized playback
- [ ] Reproducible setup with Docker Compose
- [ ] Technical writeup with performance profiling

## Development Roadmap
See [ROADMAP.md](ROADMAP.md) for 8-week implementation plan.

## Contributing
This is a research/portfolio project. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License
MIT - See [LICENSE](LICENSE) for details.
