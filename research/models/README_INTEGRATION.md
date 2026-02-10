# Dual LSTM + Fusion Model - Integration Guide

## Quick Answer: How Does This Model Fit Into The Project?

The Dual LSTM model is the **prediction engine** in Metis's automated trading pipeline:

```
┌─────────────────┐
│ Feature Pipeline│  (data_ingest/, features generation)
│   • EIA Data    │
│   • FRED Macros │
│   • Congress DB │
└────────┬────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────┐
│           Data Storage (Parquet Files)                   │
│   data/features/{train|val|test}_{daily|low_freq|sparse} │
└────────┬─────────────────────────────────────────────────┘
         │
         ▼
┌───────────────────────────────────────┐
│  Dual LSTM + Fusion (THIS MODEL)      │
│  research/models/train_dual_lstm.ipynb│
│                                       │
│  Outputs:                             │
│  • Probability (0.0 - 1.0)            │
│  • Direction (Long/Neutral)           │
│  • Confidence score                   │
└────────┬────────────────────────────────┘
         │
         │ inference_pipeline.py
         │ Converts to TradingSignal
         ▼
┌────────────────────────────────────────┐
│  Signal Client (Python)                │
│  research/signal_client.py             │
│                                        │
│  • Connects to Rust execution engine   │
│  • Sends signal via TCP + MessagePack  │
│  • Receives execution confirmation     │
└────────┬────────────────────────────────┘
         │
         │ TCP/Port 8080
         ▼
┌──────────────────────────────────────────┐
│  RUST Execution Engine                   │
│  execution/signal_interface/            │
│                                          │
│  • Validates signal                      │
│  • Places order on CME futures           │
│  • Fills and reports back                │
└──────────────────────────────────────────┘
```

---

## Key Integration Points

### 1. **Data Preparation** → Features
The model expects parquet files in `data/features/`:
```
├── train_daily_features.parquet      (5663 rows × 16 cols)
├── train_low_freq_features.parquet   (5663 rows × 37 cols)
├── train_sparse_features.parquet     (5663 rows × 5 cols)
├── test_daily_features.parquet       (981 rows × 16 cols)
├── test_low_freq_features.parquet    (981 rows × 37 cols)
└── test_sparse_features.parquet      (981 rows × 5 cols)
```

**Currently**: Data loading happens in notebook cells 1-3. Eventually, this should be replaced with real-time streaming from feature store.

### 2. **Model Training** → Weights & Scalers
After training, save:
```python
# In notebook (after training)
model.save('models/dual_lstm_v1.0.h5')

scalers = (scaler_daily, scaler_low_freq, scaler_sparse)
with open('models/scalers_v1.0.pkl', 'wb') as f:
    pickle.dump(scalers, f)
```

### 3. **Inference** → Predictions
The `inference_pipeline.py` module:
- Loads the trained model and scalers
- Preprocesses live feature data
- Runs forward pass
- Converts output to trading signal

```python
from inference_pipeline import DualLSTMInference

pipeline = DualLSTMInference(
    model_path="models/dual_lstm_v1.0.h5",
    scalers_path="models/scalers_v1.0.pkl",
)

# Generate prediction
prediction = pipeline.predict(daily_df, low_freq_df, sparse_df)
# → {"probability": 0.62, "direction": "Long", "confidence": 0.62, ...}
```

### 4. **Signal Generation** → TradingSignal Format
Pipeline converts prediction to Rust-compatible signal:

```python
signal = pipeline.prediction_to_signal(prediction)
# → {
#     "signal_id": "uuid-...",
#     "timestamp": "2026-02-10T14:30:00Z",
#     "symbol": "NG:CME",
#     "direction": "Long",
#     "confidence": 0.62,
#     "target_quantity": 10.0,
#     "horizon_minutes": 60,
#     "metadata": {...}
# }
```

### 5. **Execution** → Rust Receives & Trades
Rust execution engine:
- Listens on TCP port 8080
- Receives MessagePack-encoded signal
- Validates (confidence >= threshold, quantity <= max)
- Places order on CME
- Returns `ExecutionResponse` with fill details

```rust
// Rust side (execution/signal_interface/src/lib.rs)
pub struct TradingSignal {
    pub signal_id: String,
    pub timestamp: DateTime<Utc>,
    pub symbol: String,
    pub direction: SignalDirection,  // Long, Short, Neutral
    pub confidence: f64,
    pub target_quantity: f64,
    pub horizon_minutes: i64,
    pub metadata: SignalMetadata,
}
```

---

## How to Use the Model Today

### Option A: Batch Predictions (Development)

```python
from inference_pipeline import DualLSTMInference, load_daily_data

# Load data
daily_df, low_freq_df, sparse_df = load_daily_data("data/features")

# Initialize pipeline
pipeline = DualLSTMInference(threshold=0.40)

# Generate prediction
result = pipeline.predict_and_trade(
    daily_df,
    low_freq_df,
    sparse_df,
    dry_run=True  # Don't send to execution yet
)

print(f"Prediction: {result['prediction']}")
print(f"Confidence: {result['prediction']['confidence']:.1%}")
```

### Option B: Real-Time Inference (Production)

```python
from inference_pipeline import DualLSTMInference
import pandas as pd

# Load latest features (from feature store or database)
daily_df = get_latest_daily_features()    # Last 20 rows
low_freq_df = get_latest_low_freq_features()
sparse_df = get_latest_sparse_features()

# Initialize pipeline (once on startup)
pipeline = DualLSTMInference()

# Generate signal and send to execution
result = pipeline.predict_and_trade(
    daily_df,
    low_freq_df,
    sparse_df,
    target_quantity=10.0,
    dry_run=False  # Actually send to execution engine
)

if result['execution_response']['status'] == 'Completed':
    print(f"Order filled at {result['execution_response']['avg_fill_price']}")
```

### Option C: Backtest on Test Set

```python
from inference_pipeline import DualLSTMInference, load_daily_data
import numpy as np

pipeline = DualLSTMInference(threshold=0.40)
daily_df, low_freq_df, sparse_df = load_daily_data("data/features")

# Generate predictions for all test samples
predictions = []
for i in range(20, len(daily_df)):  # Start from lookback window
    daily_window = daily_df.iloc[i-20:i]
    low_freq_window = low_freq_df.iloc[i-20:i]
    sparse_window = sparse_df.iloc[i-20:i]
    
    pred = pipeline.predict(daily_window, low_freq_window, sparse_window)
    predictions.append(pred["probability"])

print(f"Generated {len(predictions)} predictions")

# Compare against actual labels
actual_labels = get_actual_labels()
accuracy = (np.array(predictions) > 0.40 == actual_labels).mean()
print(f"Backtest accuracy: {accuracy:.1%}")
```

---

## Current Status: Development → Production

### ✅ Complete
- [x] Model architecture designed and trained
- [x] 76.5% accuracy achieved
- [x] Integration interface defined (TradingSignal format)
- [x] Signal client implemented
- [x] Configuration management system ready
- [x] Inference pipeline module created

### 🔄 In Progress
- [ ] Save trained model weights (from notebook)
- [ ] Save scalers for inference
- [ ] Integration testing with mock execution engine
- [ ] Deployment to staging environment

### ⏳ To Do
- [ ] **Real-time feature pipeline** (currently notebook-based)
  - Automate EIA weekly report ingestion
  - Stream FRED data updates
  - Real-time Congress activity monitor
  
- [ ] **Live backtest** on recent out-of-sample data (2026-01 to present)
  
- [ ] **Performance monitoring**
  - Track prediction accuracy over time
  - Monitor latency (target: <100ms end-to-end)
  - Alert on accuracy drift
  
- [ ] **Ensemble improvements**
  - Stack XGBoost on LSTM outputs
  - Combine with momentum/mean-reversion baselines
  
- [ ] **Production deployment**
  - Container (Docker)
  - CI/CD pipeline for model updates
  - A/B testing framework

---

## File Structure

```
research/models/
├── train_dual_lstm_fusion.ipynb     ← Training notebook (primary)
├── train_lstm.ipynb                 ← Baseline (archived)
│
├── inference_pipeline.py             ← Production inference module
│
├── config/
│   └── model_config.yaml             ← Model hyperparameters & metadata
│
├── models/                           ← (Create these after training)
│   ├── dual_lstm_v1.0.h5            ← TensorFlow model weights
│   └── scalers_v1.0.pkl             ← StandardScaler objects
│
└── archive/
    └── baseline_results.csv           ← Historical performance logs
```

---

## Next Steps: Moving to Production

### Week 1-2: Model Export & Testing
1. **Save model artifacts**
   ```python
   # At end of train_dual_lstm_fusion.ipynb
   model.save('models/dual_lstm_v1.0.h5')
   pickle.dump((scaler_daily, scaler_low_freq, scaler_sparse), 
               open('models/scalers_v1.0.pkl', 'wb'))
   ```

2. **Test inference pipeline**
   ```bash
   python inference_pipeline.py --dry-run
   ```

3. **Integration test** with mock Rust server

### Week 3: Real-Time Feature Pipeline
1. Automate feature generation from live data sources
2. Replace notebook-based data prep with production job scheduler
3. Stream features to inference engine

### Week 4: Deployment & Monitoring
1. Deploy to staging environment
2. Live validation on recent data
3. Set up monitoring dashboards
4. Plan rollout schedule

---

## FAQ

**Q: How often does the model retrain?**  
A: Currently manual. After live validation, recommend weekly retraining on new data.

**Q: What's the latency from signal generation to execution?**  
A: Target is <100ms Python inference + <50ms network + <50ms Rust execution = ~200ms total. Monitor with `latency_ms` field in `ExecutionResponse`.

**Q: Can I change the threshold?**  
A: Yes, any value 0.0-1.0 works. 0.40 was optimized for F1 on training data. Try 0.30 for higher recall or 0.50 for higher precision.

**Q: What if features are missing/sparse?**  
A: Model requires exactly 20 days of lookback. If data is incomplete, inference will fail. Fallback to neutral signal or skip prediction.

**Q: How do I update to a new model version?**  
A: Update `model_config.yaml` with new version number, save new model files, then point `inference_pipeline.py` to them.

---

## Quick Start (5 minutes)

```bash
# 1. Train model (in Jupyter)
jupyter notebook research/models/train_dual_lstm_fusion.ipynb
# Run all cells, save model at the end

# 2. Test inference
cd research/models
python inference_pipeline.py --dry-run

# 3. Send live signal (if Rust engine running)
python -c "
from inference_pipeline import DualLSTMInference, load_daily_data
pipeline = DualLSTMInference()
d, lf, s = load_daily_data('data/features')
result = pipeline.predict_and_trade(d, lf, s, dry_run=False)
print(result['execution_response'])
"
```

---

**Last Updated**: 2026-02-10  
**Model Version**: 1.0  
**Status**: Ready for integration testing
