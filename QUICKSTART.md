# Metis: Quick Start Guide (First 3 Days)

This guide walks you through the MVP setup in 3 days, as outlined in the roadmap.

---

## Day 1: Data Infrastructure (4-6 hours)

### Goal
Set up TimescaleDB, ingest 1 week of sample tick data, and test weather API.

### Step 1.1: Start Infrastructure (15 minutes)
```bash
cd infrastructure
docker-compose up -d

# Wait for services to start
timeout /t 30

# Verify database
docker exec -it metis-timescaledb psql -U postgres -d metis -c "SELECT * FROM market_data LIMIT 5;"
```

### Step 1.2: Acquire Sample Tick Data (1-2 hours)

**Option A: Databento (Recommended)**
1. Sign up: https://databento.com/signup
2. Get API key from dashboard
3. Install client: `pip install databento`
4. Download sample data:

```python
# research/data_ingest/download_databento.py
import databento as db

client = db.Historical('YOUR_API_KEY')

# Download 1 week of Natural Gas futures
data = client.timeseries.get_range(
    dataset='GLBX.MDP3',  # CME Globex
    symbols=['NGZ24'],     # Dec 2024 Natural Gas
    schema='mbp-1',        # Market by price (L2)
    start='2024-01-01',
    end='2024-01-07',
)

data.to_csv('data/tick_data/NGZ24_20240101_20240107.csv')
print(f"Downloaded {len(data)} ticks")
```

**Option B: Use Sample CSV**
If you don't have access yet, create sample data:
```python
# research/data_ingest/generate_sample_data.py
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Generate realistic tick data
start_time = datetime(2024, 1, 1, 9, 0)
num_ticks = 10000
base_price = 2.50

timestamps = [start_time + timedelta(seconds=i) for i in range(num_ticks)]
prices = base_price + np.random.randn(num_ticks).cumsum() * 0.001

df = pd.DataFrame({
    'timestamp': timestamps,
    'symbol': 'NGZ24',
    'bid': prices - 0.002,
    'ask': prices + 0.002,
    'bid_quantity': np.random.randint(50, 200, num_ticks),
    'ask_quantity': np.random.randint(50, 200, num_ticks),
    'last': prices,
    'volume': np.random.randint(1, 50, num_ticks),
})

df.to_csv('data/tick_data/NGZ24_sample.csv', index=False)
print(f"Generated {len(df)} sample ticks")
```

### Step 1.3: Load Tick Data into Database (30 minutes)
```python
# research/data_ingest/load_to_db.py
import pandas as pd
from sqlalchemy import create_engine
from config import DB_URL

# Read tick data
df = pd.read_csv('data/tick_data/NGZ24_sample.csv')
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Calculate spread
df['spread_bps'] = ((df['ask'] - df['bid']) / ((df['bid'] + df['ask']) / 2)) * 10000

# Load to database
engine = create_engine(DB_URL)
df.to_sql('market_data', engine, if_exists='append', index=False)

print(f"Loaded {len(df)} ticks to database")

# Verify
result = pd.read_sql("SELECT COUNT(*) FROM market_data", engine)
print(f"Total ticks in DB: {result.iloc[0, 0]}")
```

Run it:
```bash
cd research
python data_ingest/load_to_db.py
```

### Step 1.4: Test Weather API (30 minutes)
```bash
python features/climate_features.py
```

Expected output: DataFrame with temperature, HDD/CDD, etc.

### Day 1 Checklist
- [ ] Docker containers running
- [ ] Database has market_data table with ticks
- [ ] Can fetch weather data from Open-Meteo
- [ ] Data stored in both CSV (Parquet) and PostgreSQL

---

## Day 2: Rust Order Book Parser (4-6 hours)

### Goal
Build a working order book simulator that processes tick data and calculates VWAP.

### Step 2.1: Test Existing Order Book (15 minutes)
```bash
cd execution/orderbook
cargo test -- --nocapture
```

All tests should pass. Review the output to understand order book operations.

### Step 2.2: Add CSV Parser (1 hour)
Create `execution/orderbook/src/csv_parser.rs`:

```rust
use anyhow::Result;
use chrono::DateTime;
use csv::ReaderBuilder;
use std::path::Path;
use super::{MarketEvent, EventType};

pub struct CsvTickParser;

impl CsvTickParser {
    pub fn parse_file(path: &Path) -> Result<Vec<MarketEvent>> {
        let mut reader = ReaderBuilder::new()
            .has_headers(true)
            .from_path(path)?;
        
        let mut events = Vec::new();
        
        for result in reader.records() {
            let record = result?;
            
            let timestamp: DateTime<chrono::Utc> = record[0].parse()?;
            let bid: f64 = record[2].parse()?;
            let ask: f64 = record[3].parse()?;
            let bid_qty: f64 = record[4].parse()?;
            let ask_qty: f64 = record[5].parse()?;
            
            events.push(MarketEvent {
                timestamp,
                event_type: EventType::Quote {
                    bid_price: bid,
                    bid_quantity: bid_qty,
                    ask_price: ask,
                    ask_quantity: ask_qty,
                },
            });
        }
        
        Ok(events)
    }
}
```

Add to `lib.rs`:
```rust
mod csv_parser;
pub use csv_parser::CsvTickParser;
```

### Step 2.3: Add LOB Parser Binary (1 hour)
Create `execution/orderbook/src/bin/lob_parser.rs`:

```rust
use anyhow::Result;
use orderbook::{OrderBook, CsvTickParser};
use std::path::PathBuf;
use tracing::{info, Level};
use clap::Parser;

#[derive(Parser)]
struct Args {
    #[arg(short, long)]
    input: PathBuf,
}

fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_max_level(Level::INFO)
        .init();

    let args = Args::parse();
    
    info!("Parsing tick data from {:?}", args.input);
    let events = CsvTickParser::parse_file(&args.input)?;
    info!("Parsed {} events", events.len());
    
    let mut book = OrderBook::new("NG:CME".to_string());
    
    for event in events {
        book.process_event(event)?;
    }
    
    // Print final book state
    if let (Some((bid, bid_qty)), Some((ask, ask_qty))) = (book.best_bid(), book.best_ask()) {
        info!("Final book state:");
        info!("  Best bid: ${:.4} x {}", bid, bid_qty);
        info!("  Best ask: ${:.4} x {}", ask, ask_qty);
        info!("  Mid: ${:.4}", book.mid_price().unwrap());
        info!("  Spread: {:.2} bps", book.spread_bps().unwrap());
    }
    
    Ok(())
}
```

Add dependencies to `orderbook/Cargo.toml`:
```toml
[dependencies]
csv = "1.3"
clap = { version = "4.4", features = ["derive"] }
```

### Step 2.4: Run Parser on Sample Data (15 minutes)
```bash
cargo build --release
cargo run --release --bin lob_parser -- --input ../../data/tick_data/NGZ24_sample.csv
```

Expected output: Final book state with bid/ask/spread.

### Step 2.5: Add VWAP Calculator (1 hour)
Create `execution/orderbook/src/bin/vwap_calculator.rs`:

```rust
use anyhow::Result;
use orderbook::{OrderBook, CsvTickParser, Side};
use std::path::PathBuf;
use chrono::Duration;
use clap::Parser;

#[derive(Parser)]
struct Args {
    #[arg(short, long)]
    input: PathBuf,
    
    #[arg(short, long, default_value = "15")]
    window_minutes: i64,
}

fn main() -> Result<()> {
    let args = Args::parse();
    
    let events = CsvTickParser::parse_file(&args.input)?;
    let mut book = OrderBook::new("NG:CME".to_string());
    
    let window = Duration::minutes(args.window_minutes);
    let mut window_mids = Vec::new();
    let mut window_volumes = Vec::new();
    
    let start_time = events[0].timestamp;
    
    for event in events {
        book.process_event(event.clone())?;
        
        if event.timestamp - start_time <= window {
            if let Some(mid) = book.mid_price() {
                window_mids.push(mid);
                window_volumes.push(1.0); // Simplified
            }
        }
    }
    
    // Calculate VWAP
    let total_volume: f64 = window_volumes.iter().sum();
    let vwap: f64 = window_mids.iter()
        .zip(window_volumes.iter())
        .map(|(price, vol)| price * vol)
        .sum::<f64>() / total_volume;
    
    println!("VWAP over {} minutes: ${:.4}", args.window_minutes, vwap);
    
    Ok(())
}
```

Run it:
```bash
cargo run --release --bin vwap_calculator -- --input ../../data/tick_data/NGZ24_sample.csv --window-minutes 15
```

### Day 2 Checklist
- [ ] Order book tests pass
- [ ] CSV parser reads tick data
- [ ] LOB parser processes full file
- [ ] VWAP calculator works over 15-minute windows
- [ ] Processing >1000 ticks/second

---

## Day 3: Baseline ML Model (4-6 hours)

### Goal
Train a simple LSTM to predict next-hour Natural Gas price direction using weather data.

### Step 3.1: Fetch Weather Data (1 hour)
```python
# research/data_ingest/fetch_weather_for_training.py
import pandas as pd
from features.climate_features import ClimateFeatureEngine, REGION_COORDS
from datetime import datetime, timedelta

engine = ClimateFeatureEngine(regions=["PERMIAN"])

# Fetch 3 months of data
end_date = datetime.now()
start_date = end_date - timedelta(days=90)

coords = REGION_COORDS["PERMIAN"]
df = engine.fetch_openmeteo_data(
    latitude=coords["lat"],
    longitude=coords["lon"],
    start_date=start_date.strftime("%Y-%m-%d"),
    end_date=end_date.strftime("%Y-%m-%d"),
)

# Engineer features
features = engine.engineer_features(df)
features.to_parquet("data/processed/weather_features_3months.parquet")

print(f"Saved {len(features)} hourly weather observations")
```

Run it:
```bash
cd research
python data_ingest/fetch_weather_for_training.py
```

### Step 3.2: Prepare Training Data (1 hour)
```python
# research/models/prepare_training_data.py
import pandas as pd
from sqlalchemy import create_engine
from config import DB_URL

# Load market data
engine = create_engine(DB_URL)
market_df = pd.read_sql(
    "SELECT * FROM market_data WHERE timestamp >= NOW() - INTERVAL '90 days' ORDER BY timestamp",
    engine
)

# Resample to hourly
market_df['timestamp'] = pd.to_datetime(market_df['timestamp'])
hourly = market_df.set_index('timestamp').resample('1H').agg({
    'last': 'last',
    'volume': 'sum',
    'spread_bps': 'mean',
}).dropna()

# Load weather
weather_df = pd.read_parquet("data/processed/weather_features_3months.parquet")
weather_df = weather_df.set_index('timestamp')

# Merge
combined = hourly.join(weather_df, how='inner')

# Calculate target: next-hour return
combined['returns'] = combined['last'].pct_change()
combined['target'] = (combined['returns'].shift(-1) > 0).astype(int)  # Binary: up or down

# Drop NaNs
combined = combined.dropna()

print(f"Training samples: {len(combined)}")
print(f"Feature columns: {len(combined.columns)}")
print(f"Target distribution: {combined['target'].value_counts()}")

combined.to_parquet("data/processed/training_data.parquet")
```

### Step 3.3: Train Baseline LSTM (2 hours)
```python
# research/models/train_baseline_lstm.py
import torch
import torch.nn as nn
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

# Load data
df = pd.read_parquet("data/processed/training_data.parquet")

# Select features
feature_cols = ['last', 'volume', 'spread_bps', 'temperature', 'hdd', 'cdd', 'windspeed']
X = df[feature_cols].values
y = df['target'].values

# Train/test split
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

# Normalize
scaler = StandardScaler()
X_train = scaler.fit_transform(X_train)
X_test = scaler.transform(X_test)

# Simple LSTM
class SimpleLSTM(nn.Module):
    def __init__(self, input_size, hidden_size=64):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, batch_first=True)
        self.fc = nn.Linear(hidden_size, 1)
        self.sigmoid = nn.Sigmoid()
    
    def forward(self, x):
        _, (hidden, _) = self.lstm(x)
        out = self.fc(hidden[-1])
        return self.sigmoid(out)

# Reshape for LSTM: (batch, seq_len, features)
X_train_seq = X_train.reshape(-1, 1, X_train.shape[1])
X_test_seq = X_test.reshape(-1, 1, X_test.shape[1])

# Convert to tensors
X_train_t = torch.FloatTensor(X_train_seq)
y_train_t = torch.FloatTensor(y_train).reshape(-1, 1)
X_test_t = torch.FloatTensor(X_test_seq)
y_test_t = torch.FloatTensor(y_test).reshape(-1, 1)

# Train
model = SimpleLSTM(input_size=len(feature_cols))
criterion = nn.BCELoss()
optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

epochs = 50
for epoch in range(epochs):
    model.train()
    optimizer.zero_grad()
    outputs = model(X_train_t)
    loss = criterion(outputs, y_train_t)
    loss.backward()
    optimizer.step()
    
    if (epoch + 1) % 10 == 0:
        model.eval()
        with torch.no_grad():
            test_outputs = model(X_test_t)
            test_preds = (test_outputs > 0.5).float()
            accuracy = (test_preds == y_test_t).float().mean()
        print(f"Epoch {epoch+1}/{epochs}, Loss: {loss.item():.4f}, Test Acc: {accuracy:.4f}")

# Save model
torch.save(model.state_dict(), "models/baseline_lstm_v1.pth")
print("Model saved to models/baseline_lstm_v1.pth")
```

Run it:
```bash
python models/prepare_training_data.py
python models/train_baseline_lstm.py
```

Expected output: Test accuracy >0.50 (better than random).

### Day 3 Checklist
- [ ] Weather data fetched for 3 months
- [ ] Training data prepared with market + weather features
- [ ] Baseline LSTM trained with >50% accuracy
- [ ] Model saved to disk
- [ ] Can generate predictions for new data

---

## Summary: What You've Built

After 3 days, you have:

1. **Data Infrastructure**: TimescaleDB with tick data, weather features
2. **Rust Engine**: Order book simulator, CSV parser, VWAP calculator
3. **ML Baseline**: LSTM predicting next-hour price direction

## Next Steps (Week 2+)

- Week 2: Connect Python signals → Rust execution engine
- Week 3: Implement TWAP algorithm with actual slicing
- Week 4: Add RAG explanations for signals
- Week 5-6: Build full backtest harness
- Week 7-8: Create Tauri UI for visualization

See [ROADMAP.md](ROADMAP.md) for complete 8-week plan.

---

## Troubleshooting

**Problem**: Can't download Databento data
- Use sample data generator instead
- Or request free trial extension

**Problem**: LSTM accuracy is 50% (random)
- Check target distribution (should be ~50/50 up/down)
- Add more features (lagged returns, rolling volatility)
- Increase training epochs or model complexity

**Problem**: Rust build fails
- Update Rust: `rustup update`
- Clean build: `cargo clean && cargo build`

**Problem**: Out of memory during training
- Reduce training data to 1 month
- Use smaller batch size
- Downsample to 4-hour bars instead of hourly

---

## Validation

Run these commands to verify everything works:

```bash
# Database has data
docker exec -it metis-timescaledb psql -U postgres -d metis -c "SELECT COUNT(*) FROM market_data;"

# Rust tests pass
cd execution && cargo test --all

# Python can load trained model
python -c "import torch; model = torch.load('models/baseline_lstm_v1.pth'); print('Model loaded OK')"

# End-to-end: Generate signal and send to Rust (Week 2 task)
```
