-- Initialize Metis database schema
-- Creates hypertables for time-series data

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Market tick data table
CREATE TABLE IF NOT EXISTS market_data (
    timestamp TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    bid DOUBLE PRECISION,
    ask DOUBLE PRECISION,
    last DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    bid_quantity DOUBLE PRECISION,
    ask_quantity DOUBLE PRECISION,
    spread_bps DOUBLE PRECISION,
    PRIMARY KEY (timestamp, symbol)
);

-- Convert to hypertable
SELECT create_hypertable('market_data', 'timestamp', if_not_exists => TRUE);

-- Climate features table
CREATE TABLE IF NOT EXISTS climate_features (
    timestamp TIMESTAMPTZ NOT NULL,
    region VARCHAR(50) NOT NULL,
    temperature DOUBLE PRECISION,
    temp_forecast DOUBLE PRECISION,
    temp_actual DOUBLE PRECISION,
    temp_error DOUBLE PRECISION,
    hdd DOUBLE PRECISION,
    cdd DOUBLE PRECISION,
    heating_degree_days DOUBLE PRECISION,
    windspeed DOUBLE PRECISION,
    precipitation DOUBLE PRECISION,
    PRIMARY KEY (timestamp, region)
);

SELECT create_hypertable('climate_features', 'timestamp', if_not_exists => TRUE);

-- Grid metrics table
CREATE TABLE IF NOT EXISTS grid_metrics (
    timestamp TIMESTAMPTZ NOT NULL,
    node_id VARCHAR(50) NOT NULL,
    lmp DOUBLE PRECISION,  -- Locational Marginal Price
    congestion_cost DOUBLE PRECISION,
    marginal_loss DOUBLE PRECISION,
    load_mw DOUBLE PRECISION,
    PRIMARY KEY (timestamp, node_id)
);

SELECT create_hypertable('grid_metrics', 'timestamp', if_not_exists => TRUE);

-- Policy events table
CREATE TABLE IF NOT EXISTS policy_events (
    timestamp TIMESTAMPTZ NOT NULL,
    event_id VARCHAR(100) PRIMARY KEY,
    event_type VARCHAR(50),
    entity_affected VARCHAR(100),
    description TEXT,
    sentiment_score DOUBLE PRECISION,
    decay_factor DOUBLE PRECISION,
    source VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_policy_events_timestamp ON policy_events(timestamp DESC);

-- Trading signals table
CREATE TABLE IF NOT EXISTS trading_signals (
    signal_id VARCHAR(100) PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(20),
    direction VARCHAR(20),
    confidence DOUBLE PRECISION,
    target_quantity DOUBLE PRECISION,
    horizon_minutes INTEGER,
    model_version VARCHAR(50),
    features_used TEXT[],
    weather_anomaly DOUBLE PRECISION,
    policy_trigger TEXT
);

CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON trading_signals(timestamp DESC);

-- Executions table
CREATE TABLE IF NOT EXISTS executions (
    execution_id VARCHAR(100) PRIMARY KEY,
    signal_id VARCHAR(100) REFERENCES trading_signals(signal_id),
    timestamp TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(20),
    side VARCHAR(10),
    quantity DOUBLE PRECISION,
    avg_fill_price DOUBLE PRECISION,
    slippage_bps DOUBLE PRECISION,
    latency_ms INTEGER,
    status VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_executions_timestamp ON executions(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_executions_signal_id ON executions(signal_id);

-- Backtest results table
CREATE TABLE IF NOT EXISTS backtest_results (
    backtest_id VARCHAR(100) PRIMARY KEY,
    run_timestamp TIMESTAMPTZ NOT NULL,
    start_date DATE,
    end_date DATE,
    strategy_name VARCHAR(100),
    model_version VARCHAR(50),
    initial_capital DOUBLE PRECISION,
    final_pnl DOUBLE PRECISION,
    sharpe_ratio DOUBLE PRECISION,
    max_drawdown DOUBLE PRECISION,
    win_rate DOUBLE PRECISION,
    total_trades INTEGER,
    parameters JSONB
);

CREATE INDEX IF NOT EXISTS idx_backtest_timestamp ON backtest_results(run_timestamp DESC);

-- Create continuous aggregates for common queries
CREATE MATERIALIZED VIEW IF NOT EXISTS market_data_1min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', timestamp) AS bucket,
    symbol,
    first(bid, timestamp) AS open_bid,
    max(bid) AS high_bid,
    min(bid) AS low_bid,
    last(bid, timestamp) AS close_bid,
    first(ask, timestamp) AS open_ask,
    max(ask) AS high_ask,
    min(ask) AS low_ask,
    last(ask, timestamp) AS close_ask,
    sum(volume) AS total_volume,
    avg(spread_bps) AS avg_spread_bps
FROM market_data
GROUP BY bucket, symbol;

-- Refresh policy for continuous aggregate
SELECT add_continuous_aggregate_policy('market_data_1min',
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE);

-- Insert sample data for testing
INSERT INTO market_data (timestamp, symbol, bid, ask, last, volume, bid_quantity, ask_quantity, spread_bps)
VALUES 
    (NOW() - INTERVAL '1 hour', 'NG:CME', 2.500, 2.505, 2.502, 100.0, 50.0, 75.0, 20.0),
    (NOW() - INTERVAL '59 minutes', 'NG:CME', 2.501, 2.506, 2.503, 120.0, 60.0, 80.0, 19.9)
ON CONFLICT (timestamp, symbol) DO NOTHING;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO postgres;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO postgres;
