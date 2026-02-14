"""
Feature Unification Pipeline
Materialize ML-ready combined features from all sources
Output: Parquet + TimescaleDB for training
"""
import os
import sys
from pathlib import Path
import pandas as pd
import numpy as np
from sqlalchemy import create_engine
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Add project root for any shared modules
sys.path.append(str(Path(__file__).resolve().parents[1]))

load_dotenv()
DB_URL = os.getenv("DB_URL", "postgresql://postgres:postgres@localhost:5432/metis")
MODE = os.getenv("METIS_MODE", "DEV").upper()
IS_REAL = MODE == "REAL"
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
PROCESSED_DIR = DATA_DIR / ("processed" if IS_REAL else "dev/processed")

def load_ng_tick_data():
    """Load and resample NG ticks to hourly OHLCV"""
    try:
        csv_path = DATA_DIR / "tick_data" / "NGZ24_sample.csv"
        use_csv = csv_path.exists() and MODE == "REAL"
        if use_csv:
            df = pd.read_csv(csv_path)
        else:
            raise RuntimeError("Synthetic NG ticks enabled (DEV mode or missing CSV)")
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Calculate mid price
        df['mid'] = (df['bid'] + df['ask']) / 2
        
        # Resample to hourly OHLCV
        hourly = df.set_index('timestamp').resample('1h').agg({
            'mid': ['first', 'max', 'min', 'last'],
            'volume': 'sum',
            'bid': 'mean',
            'ask': 'mean',
        }).dropna()
        
        # Flatten column names
        hourly.columns = ['_'.join(col).strip() for col in hourly.columns.values]
        hourly = hourly.rename(columns={
            'mid_first': 'open',
            'mid_max': 'high',
            'mid_min': 'low',
            'mid_last': 'close',
            'volume_sum': 'volume',
            'bid_mean': 'bid',
            'ask_mean': 'ask',
        })
        
        # Engineer features
        hourly['returns'] = hourly['close'].pct_change()
        hourly['log_returns'] = np.log(hourly['close'] / hourly['close'].shift(1))
        hourly['spread'] = hourly['ask'] - hourly['bid']
        hourly['spread_bps'] = (hourly['spread'] / hourly['close']) * 10000
        
        # Rolling volatility
        hourly['volatility_1h'] = hourly['returns'].rolling(window=1).std()
        hourly['volatility_24h'] = hourly['returns'].rolling(window=24).std()
        
        # Lag features
        hourly['returns_lag1'] = hourly['returns'].shift(1)
        hourly['returns_lag24'] = hourly['returns'].shift(24)
        
        # Clean
        hourly = hourly.reset_index()
        hourly = hourly.dropna(subset=['close'])
        
        print(f"Loaded {len(hourly)} hourly NG records with engineered features")
        return hourly
    except Exception as e:
        print(f"Falling back to synthetic NG data: {e}")
        # Synthetic ticks
        start_time = pd.to_datetime('2024-01-01 09:00:00')
        num_ticks = 200000
        timestamps = [start_time + pd.Timedelta(seconds=i) for i in range(num_ticks)]
        base_price = 2.5
        prices = base_price + np.random.randn(num_ticks).cumsum() * 0.001
        df = pd.DataFrame({
            'timestamp': timestamps,
            'bid': prices - 0.001,
            'ask': prices + 0.001,
            'volume': np.random.randint(1, 50, num_ticks),
        })
        df['mid'] = (df['bid'] + df['ask']) / 2
        print("Using synthetic NG tick data (DEV mode or missing CSV)")
        return load_ng_tick_data_from_df(df)


def load_ng_tick_data_from_df(df: pd.DataFrame) -> pd.DataFrame:
    """Helper to process NG tick dataframe to hourly features"""
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    if 'mid' not in df.columns:
        df['mid'] = (df['bid'] + df['ask']) / 2
    
    # Ensure spread and mid exist
    if 'mid' not in df.columns:
        df['mid'] = (df['bid'] + df['ask']) / 2
    df['spread'] = df['ask'] - df['bid']
    df['spread_bps'] = (df['spread'] / df['mid']) * 10000

    # Resample to hourly OHLCV
    hourly = df.set_index('timestamp').resample('1h').agg({
        'mid': ['first', 'max', 'min', 'last'],
        'volume': 'sum',
        'bid': 'mean',
        'ask': 'mean',
        'spread': 'mean',
        'spread_bps': 'mean',
    }).dropna()
    
    hourly.columns = ['_'.join(col).strip() for col in hourly.columns.values]
    hourly = hourly.rename(columns={
        'mid_first': 'open',
        'mid_max': 'high',
        'mid_min': 'low',
        'mid_last': 'close',
        'volume_sum': 'volume',
        'bid_mean': 'bid',
        'ask_mean': 'ask',
        'spread_mean': 'spread',
        'spread_bps_mean': 'spread_bps',
    })
    
    hourly['returns'] = hourly['close'].pct_change()
    hourly['log_returns'] = np.log(hourly['close'] / hourly['close'].shift(1))
    hourly['volatility_1h'] = hourly['returns'].rolling(window=1).std()
    hourly['volatility_24h'] = hourly['returns'].rolling(window=24).std()
    hourly['returns_lag1'] = hourly['returns'].shift(1)
    hourly['returns_lag24'] = hourly['returns'].shift(24)
    hourly = hourly.reset_index()
    hourly = hourly.dropna(subset=['close'])
    print(f"Loaded {len(hourly)} hourly NG records with engineered features")
    return hourly

def load_grid_lmp_features():
    """Load and aggregate grid LMP data"""
    def synthetic_lmp():
        start_date = pd.to_datetime('2024-01-01')
        dates = pd.date_range(start_date, periods=8760, freq='h')
        df = pd.DataFrame({
            'timestamp': dates,
            'lmp': 30 + 10 * np.sin(np.linspace(0, 8*np.pi, 8760)) + np.random.randn(8760) * 2
        })
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df_hourly = df.set_index('timestamp').resample('1h').agg({
            'lmp': ['mean', 'min', 'max', 'std']
        })
        df_hourly.columns = ['lmp_mean', 'lmp_min', 'lmp_max', 'lmp_std']
        df_hourly = df_hourly.dropna(subset=['lmp_mean'])
        df_hourly['lmp_std'] = df_hourly['lmp_std'].fillna(0)
        df_hourly['lmp_range'] = df_hourly['lmp_max'] - df_hourly['lmp_min']
        df_hourly['lmp_change'] = df_hourly['lmp_mean'].diff()
        df_hourly['lmp_change_pct'] = df_hourly['lmp_mean'].pct_change()
        df_hourly = df_hourly.reset_index()
        print(f"Using synthetic LMP data: {len(df_hourly)} records")
        return df_hourly

    if not IS_REAL:
        return synthetic_lmp()

    try:
        engine = create_engine(DB_URL)
        query = "SELECT timestamp, lmp FROM grid_lmp ORDER BY timestamp"
        df = pd.read_sql(query, engine)
        
        if len(df) == 0:
            raise ValueError("No LMP data")
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Resample to hourly (in case sub-hourly)
        df_hourly = df.set_index('timestamp').resample('1h').agg({
            'lmp': ['mean', 'min', 'max', 'std']
        })
        
        df_hourly.columns = ['lmp_mean', 'lmp_min', 'lmp_max', 'lmp_std']
        df_hourly = df_hourly.dropna(subset=['lmp_mean'])
        df_hourly['lmp_std'] = df_hourly['lmp_std'].fillna(0)
        df_hourly['lmp_range'] = df_hourly['lmp_max'] - df_hourly['lmp_min']
        df_hourly['lmp_change'] = df_hourly['lmp_mean'].diff()
        df_hourly['lmp_change_pct'] = df_hourly['lmp_mean'].pct_change()
        
        df_hourly = df_hourly.reset_index()
        print(f"Loaded {len(df_hourly)} hourly grid LMP records")
        return df_hourly
    except Exception as e:
        print(f"Error loading grid LMP data: {e}")
        return synthetic_lmp()

def load_eia_features():
    """Load and resample EIA data to hourly"""
    def synthetic_eia():
        start_date = pd.to_datetime('2024-01-01')
        dates = pd.date_range(start_date, periods=52, freq='W')
        df = pd.DataFrame({
            'timestamp': dates,
            'storage_bcf': 2000 + 100 * np.sin(np.linspace(0, 4*np.pi, 52)) + np.random.randn(52) * 20
        })
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df_hourly = df.set_index('timestamp').resample('1h').ffill()
        df_hourly['storage_change'] = df_hourly['storage_bcf'].diff()
        df_hourly['storage_change_pct'] = df_hourly['storage_bcf'].pct_change()
        df_hourly = df_hourly.reset_index()
        print(f"Using synthetic EIA data: {len(df_hourly)} records")
        return df_hourly

    if not IS_REAL:
        return synthetic_eia()

    try:
        engine = create_engine(DB_URL)
        query = "SELECT timestamp, storage_bcf FROM eia_storage ORDER BY timestamp"
        df = pd.read_sql(query, engine)
        
        if len(df) == 0:
            raise ValueError("No EIA data")
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Forward fill to hourly (EIA is weekly)
        df_hourly = df.set_index('timestamp').resample('1h').ffill()
        df_hourly['storage_change'] = df_hourly['storage_bcf'].diff()
        df_hourly['storage_change_pct'] = df_hourly['storage_bcf'].pct_change()
        
        df_hourly = df_hourly.reset_index()
        print(f"Loaded {len(df_hourly)} hourly EIA records (forward-filled from weekly)")
        return df_hourly
    except Exception as e:
        print(f"Error loading EIA data: {e}")
        return synthetic_eia()

def load_fred_features():
    """Load and resample FRED macro data to hourly"""
    def synthetic_fred():
        start_date = pd.to_datetime('2024-01-01')
        dates = pd.date_range(start_date, periods=365, freq='D')
        df = pd.DataFrame({
            'timestamp': dates,
            'series_id': 'INDPRO',
            'value': 100 + 2 * np.sin(np.linspace(0, 4*np.pi, 365)) + np.random.randn(365) * 0.5
        })
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df_pivot = df.pivot_table(index='timestamp', columns='series_id', values='value', aggfunc='mean')
        df_pivot = df_pivot.ffill().bfill()
        df_hourly = df_pivot.resample('1h').ffill()
        df_hourly.columns = [f'fred_{col}' for col in df_hourly.columns]
        df_hourly = df_hourly.reset_index()
        print(f"Using synthetic FRED data: {len(df_hourly)} records")
        return df_hourly

    if not IS_REAL:
        return synthetic_fred()

    try:
        engine = create_engine(DB_URL)
        query = "SELECT timestamp, series_id, value FROM fred_macro ORDER BY timestamp"
        df = pd.read_sql(query, engine)
        
        if len(df) == 0:
            raise ValueError("No FRED data")
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Pivot to wide format
        df_pivot = df.pivot_table(index='timestamp', columns='series_id', values='value', aggfunc='mean')
        
        # Forward fill (macro data is sparse)
        df_pivot = df_pivot.ffill().bfill()
        
        # Resample to hourly
        df_hourly = df_pivot.resample('1h').ffill()
        
        # Rename columns to avoid conflicts
        df_hourly.columns = [f'fred_{col}' for col in df_hourly.columns]
        
        df_hourly = df_hourly.reset_index()
        print(f"Loaded {len(df_hourly)} hourly FRED records with {len(df_hourly.columns)-1} series")
        return df_hourly
    except Exception as e:
        print(f"Error loading FRED data: {e}")
        return synthetic_fred()

def unify_features(ng_df, lmp_df, eia_df, fred_df):
    """
    Merge all data sources on timestamp
    Use NG as base (finest granularity)
    """
    print("\nUnifying features...")
    
    # Start with NG as base
    combined = ng_df.copy()
    
    # Merge grid LMP (left join on timestamp)
    if len(lmp_df) > 0:
        combined = combined.merge(lmp_df, on='timestamp', how='left')
    
    # Merge EIA
    if len(eia_df) > 0:
        combined = combined.merge(eia_df, on='timestamp', how='left')
    
    # Merge FRED
    if len(fred_df) > 0:
        combined = combined.merge(fred_df, on='timestamp', how='left')
    
    # Forward/backward fill for sparse sources and zero-fill any remaining gaps to keep DEV data
    combined = combined.ffill().bfill().fillna(0)
    
    print(f"\nCombined shape: {combined.shape}")
    print(f"Features: {combined.columns.tolist()}")
    
    return combined

def save_features(combined_df):
    """Save unified features to Parquet and database"""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    
    # Save to Parquet (mode-scoped)
    parquet_path = PROCESSED_DIR / "training_data_unified.parquet"
    combined_df.to_parquet(parquet_path, index=False)
    print(f"\nSaved {len(combined_df)} unified training records to {parquet_path}")
    
    # Save to database only in REAL mode
    if IS_REAL:
        try:
            engine = create_engine(DB_URL)
            combined_df.to_sql('training_data_unified', engine, if_exists='replace', index=False)
            print("Saved unified features to TimescaleDB (training_data_unified table)")
        except Exception as e:
            print(f"Warning: Could not save to database: {e}")
    else:
        print("Skipping database write in DEV mode")
    
    # Print summary statistics
    print("\nFeature Summary Statistics:")
    print(combined_df[['timestamp', 'close', 'volume', 'returns']].describe())
    
    return parquet_path

def main():
    """Main entry point for feature unification pipeline."""
    print("="*60)
    print("Feature Unification Pipeline")
    print("="*60)
    
    # Load all sources
    ng_df = load_ng_tick_data()
    lmp_df = load_grid_lmp_features()
    eia_df = load_eia_features()
    fred_df = load_fred_features()
    
    if len(ng_df) == 0:
        print("Error: No NG data available. Exiting.")
        exit(1)
    
    # Unify
    combined = unify_features(ng_df, lmp_df, eia_df, fred_df)
    
    # Save
    path = save_features(combined)
    
    print("\n" + "="*60)
    print(f"Unified training data ready at: {path}")
    print("="*60)
    
    return True

if __name__ == "__main__":
    main()
