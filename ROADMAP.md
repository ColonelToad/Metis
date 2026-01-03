# Metis Development Roadmap

## 8-Week MVP Implementation

### Weeks 1-2: Data Infrastructure + Instrument Selection

**Objectives:**
- Choose CME Henry Hub Natural Gas (NG) futures as primary instrument
- Set up TimescaleDB with historical tick data
- Establish data ingestion pipelines for 10+ sources

**Deliverables:**
- [ ] CME NG futures tick data (1 year historical via DataMine/Databento)
- [ ] Open-Meteo weather API integration (hourly forecasts + actuals)
- [ ] PJM real-time LMP via GridStatus.io API
- [ ] EIA natural gas storage reports ingestion
- [ ] FRED macro indicators feed
- [ ] Congress.gov + Finnhub congressional trades parser
- [ ] TimescaleDB schema with hypertables
- [ ] Parquet archive for raw tick data

**Data Schema:**
```sql
-- market_data: timestamp, bid, ask, last, volume, spread_bps
-- climate_features: timestamp, temp_forecast, temp_actual, forecast_error, heating_degree_days
-- grid_metrics: timestamp, node_id, lmp, congestion_cost, marginal_loss
-- policy_events: timestamp, event_type, entity_affected, sentiment_score, decay_factor
```

---

### Weeks 3-4: Baseline Models + Backtesting Harness

**Objectives:**
- Train LSTM hybrid for next-hour NG price direction prediction
- Build transaction cost-aware backtesting framework
- Establish performance baseline without climate features

**Deliverables:**
- [ ] Feature engineering pipeline (lagged returns, volatility, weather errors, EIA surprises)
- [ ] LSTM/Transformer hybrid architecture with confidence scoring
- [ ] Baseline models: momentum, mean reversion
- [ ] Backtest harness modeling CME spread (0.5-2 ticks), exchange fees ($1.50/side)
- [ ] Walk-forward validation on 6 months held-out data
- [ ] Performance metrics: Sharpe, max drawdown, win rate, net PnL

**Key Metric:** Achieve Sharpe >0.5 with climate features vs baseline

---

### Weeks 5-6: Rust Execution Layer

**Objectives:**
- Build order book simulator from PCAP tick data
- Implement TWAP/VWAP execution algorithms
- Create Python → Rust signal bridge

**Deliverables:**
- [ ] PCAP parser for CME tick data → Rust structs
- [ ] L2 order book reconstruction with nanosecond timestamps
- [ ] TWAP execution module (15-minute slicing)
- [ ] Execution quality metrics: arrival price vs VWAP, slippage, tracking error
- [ ] Real-time simulation mode (1000x speed playback)
- [ ] Python signal → Rust TCP/JSON bridge
- [ ] FIX 4.2/4.4 session handler using `forgefix` crate
- [ ] Latency profiling: signal generation → transmission → execution → fill

**Key Metric:** <5% TWAP tracking error, <100ms end-to-end latency

---

### Weeks 7-8: RAG Integration + UI

**Objectives:**
- Index policy/weather document corpus for retrieval
- Build Tauri + React dashboard with playback capabilities
- Integrate LLM explanations for trading signals

**Deliverables:**
- [ ] Vector DB setup (Milvus/Weaviate) with sentence-transformers
- [ ] Document corpus: 100+ EIA reports, congressional bills, FERC orders, weather advisories
- [ ] RAG query pipeline: retrieve top-3 docs + LLM summary per signal
- [ ] Tauri desktop app with Rust backend
- [ ] React frontend components:
  - Signal timeline with confidence bands
  - NG price chart with execution markers
  - Order book heatmap
  - RAG explanation panel
  - Backtest playback controls
- [ ] WebSocket for real-time simulation updates

**Key Metric:** 90%+ RAG retrieval relevance, <2s per query

---

## Post-MVP Enhancements

### Phase 2: Advanced Features (Weeks 9-12)
- Multi-asset expansion: PJM day-ahead electricity, RBOB gasoline
- Reinforcement learning for adaptive execution
- Real-time order flow toxicity detection
- Multi-threaded execution with NUMA awareness

### Phase 3: Production Readiness (Weeks 13-16)
- Co-location simulation with network jitter modeling
- Risk management: position limits, VaR, stress testing
- Compliance logging for audit trails
- Paper trading mode with simulated broker

### Phase 4: Research Extensions
- Transformer-based policy signal extraction
- Causal inference for weather → price relationships
- Cross-market arbitrage (NG futures vs PJM nodal)
- Optimal liquidation under transaction costs

---

## Milestones & Review Points

**Week 2 Review:** Data infrastructure validated, 1 week of tick data loaded
**Week 4 Review:** Baseline ML model trained, backtest framework operational
**Week 6 Review:** Rust execution layer processes historical ticks with quality metrics
**Week 8 Review:** Full system demo with UI, RAG explanations, and writeup

---

## Risk Mitigation

**Data Access Risks:**
- Backup: If CME DataMine unavailable, use Databento or IQFeed replay
- Alternative instruments: RBOB gasoline, WTI crude if NG data inaccessible

**Technical Risks:**
- Rust learning curve: Start with simple order book before FIX protocol
- LLM API costs: Use local models (Llama 3, Mistral) for RAG if budget constrained

**Scope Creep:**
- Focus on single instrument (NG) for MVP
- Defer multi-asset, RL, and co-location features to Phase 2
