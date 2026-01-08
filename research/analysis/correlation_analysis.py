"""
Correlation & Lead/Lag Analysis
Quantify predictive value of alternative data sources vs NG price returns
"""
import os
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DB_URL", "postgresql://postgres:postgres@localhost:5432/metis")
MODE = os.getenv("METIS_MODE", "DEV").upper()
IS_REAL = MODE == "REAL"
BASE_DIR = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = BASE_DIR / "analysis"
if not IS_REAL:
    ANALYSIS_DIR = ANALYSIS_DIR / "dev"

def load_ng_tick_data():
    """Load NG tick data from CSV (NGZ24_sample.csv)"""
    csv_path = BASE_DIR / "data" / "tick_data" / "NGZ24_sample.csv"
    use_csv = csv_path.exists() and MODE == "REAL"
    if use_csv:
        df = pd.read_csv(csv_path)
    else:
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
            'spread_bps': np.random.rand(num_ticks) * 10,
        })
        print("Using synthetic NG tick data (DEV mode or missing CSV)")

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['mid_price'] = (df['bid'] + df['ask']) / 2
    if 'spread_bps' not in df.columns:
        df['spread_bps'] = ((df['ask'] - df['bid']) / df['mid_price']) * 10000
    df['returns'] = df['mid_price'].pct_change()
    df['log_returns'] = np.log(df['mid_price'] / df['mid_price'].shift(1))
    
    df_hourly = df.set_index('timestamp').resample('1h').agg({
        'mid_price': 'last',
        'returns': 'sum',
        'log_returns': 'sum',
        'volume': 'sum',
        'spread_bps': 'mean'
    }).dropna()
    
    print(f"Loaded {len(df_hourly)} hourly NG records")
    return df_hourly

def load_eia_data():
    """Load EIA storage/production data from database"""
    def synthetic_eia():
        start_date = pd.to_datetime('2024-01-01')
        dates = pd.date_range(start_date, periods=52, freq='W')
        storage = 2000 + 100 * np.sin(np.linspace(0, 4*np.pi, 52)) + np.random.randn(52) * 20
        df = pd.DataFrame({'timestamp': dates, 'storage_bcf': storage})
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['storage_change'] = df['storage_bcf'].diff()
        df['storage_change_pct'] = df['storage_bcf'].pct_change()
        print(f"Using synthetic EIA data: {len(df)} records")
        return df.set_index('timestamp')

    if not IS_REAL:
        return synthetic_eia()

    try:
        engine = create_engine(DB_URL)
        
        # Try to load from database
        query = "SELECT timestamp, storage_bcf FROM eia_storage ORDER BY timestamp DESC LIMIT 200"
        df = pd.read_sql(query, engine)
        
        if len(df) == 0:
            raise ValueError("No EIA data")
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['storage_change'] = df['storage_bcf'].diff()
        df['storage_change_pct'] = df['storage_bcf'].pct_change()
        
        print(f"Loaded {len(df)} EIA records")
        return df.set_index('timestamp')
    except Exception as e:
        print(f"Error loading EIA data: {e}")
        return synthetic_eia()

def load_fred_data():
    """Load FRED macro data from database"""
    def synthetic_fred():
        start_date = pd.to_datetime('2024-01-01')
        dates = pd.date_range(start_date, periods=365, freq='D')
        df = pd.DataFrame({
            'timestamp': dates,
            'series_id': 'UNRATE',
            'value': 3.5 + 0.5 * np.sin(np.linspace(0, 4*np.pi, 365)) + np.random.randn(365) * 0.1
        })
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df_pivot = df.pivot_table(index='timestamp', columns='series_id', values='value', aggfunc='mean')
        df_pivot = df_pivot.ffill()
        print(f"Using synthetic FRED data: {len(df_pivot)} records")
        return df_pivot

    if not IS_REAL:
        return synthetic_fred()

    try:
        engine = create_engine(DB_URL)
        
        query = "SELECT timestamp, series_id, value FROM fred_macro WHERE series_id IN ('UNRATE', 'CPIENGSL', 'INDPRO') ORDER BY timestamp DESC LIMIT 500"
        df = pd.read_sql(query, engine)
        
        if len(df) == 0:
            raise ValueError("No FRED data")
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Pivot to get each series as column
        df_pivot = df.pivot_table(index='timestamp', columns='series_id', values='value', aggfunc='mean')
        df_pivot = df_pivot.ffill()  # Forward fill missing values
        
        print(f"Loaded {len(df_pivot)} FRED records with {len(df_pivot.columns)} series")
        return df_pivot
    except Exception as e:
        print(f"Error loading FRED data: {e}")
        return synthetic_fred()

def load_grid_lmp_data():
    """Load grid LMP data from database"""
    def synthetic_lmp():
        start_date = pd.to_datetime('2024-01-01')
        dates = pd.date_range(start_date, periods=8760, freq='h')
        lmp = 30 + 10 * np.sin(np.linspace(0, 8*np.pi, 8760)) + np.random.randn(8760) * 2
        df = pd.DataFrame({'timestamp': dates, 'lmp': lmp})
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['lmp_change'] = df['lmp'].diff()
        df['lmp_change_pct'] = df['lmp'].pct_change()
        print(f"Using synthetic LMP data: {len(df)} records")
        return df.set_index('timestamp')

    if not IS_REAL:
        return synthetic_lmp()

    try:
        engine = create_engine(DB_URL)
        
        query = "SELECT timestamp, lmp FROM grid_lmp ORDER BY timestamp DESC LIMIT 1000"
        df = pd.read_sql(query, engine)
        
        if len(df) == 0:
            raise ValueError("No grid LMP data")
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['lmp_change'] = df['lmp'].diff()
        df['lmp_change_pct'] = df['lmp'].pct_change()
        
        print(f"Loaded {len(df)} grid LMP records")
        return df.set_index('timestamp')
    except Exception as e:
        print(f"Error loading grid LMP data: {e}")
        return synthetic_lmp()

def compute_correlations(ng_returns, sources):
    """
    Compute contemporaneous and lagged correlations
    sources: dict of {name: series}
    """
    results = []
    
    for lag in range(0, 168, 24):  # 0 to 168 hours (7 days) in 1-day increments
        for name, source_data in sources.items():
            if len(source_data) == 0:
                continue
            
            # Align on common index
            source_lagged = source_data.shift(lag)
            common_idx = ng_returns.index.intersection(source_lagged.index)
            
            if len(common_idx) < 10:
                continue
            
            ng_subset = ng_returns.loc[common_idx]
            source_subset = source_lagged.loc[common_idx]
            
            # Handle multiple columns in source
            if isinstance(source_subset, pd.DataFrame):
                for col in source_subset.columns:
                    if source_subset[col].std() > 0:
                        corr = ng_subset.corr(source_subset[col])
                        results.append({
                            'source': f"{name}:{col}",
                            'lag_hours': lag,
                            'correlation': corr,
                            'n_samples': len(common_idx)
                        })
            else:
                if source_subset.std() > 0:
                    corr = ng_subset.corr(source_subset)
                    results.append({
                        'source': name,
                        'lag_hours': lag,
                        'correlation': corr,
                        'n_samples': len(common_idx)
                    })
    
    return pd.DataFrame(results)

def visualize_correlations(corr_df):
    """Create correlation heatmap and lag analysis"""
    # Pivot for heatmap: sources vs lags
    pivot_df = corr_df.pivot_table(index='source', columns='lag_hours', values='correlation', aggfunc='mean')
    
    fig, axes = plt.subplots(2, 1, figsize=(12, 10))
    
    # Heatmap
    sns.heatmap(pivot_df, annot=True, fmt='.3f', cmap='RdBu_r', center=0, ax=axes[0], 
                cbar_kws={'label': 'Correlation with NG Returns'})
    axes[0].set_title('Lead/Lag Correlation: Alternative Data vs NG Hourly Returns')
    axes[0].set_xlabel('Lag (hours)')
    axes[0].set_ylabel('Data Source')
    
    # Top correlations by lag
    top_by_lag = corr_df.nlargest(10, 'correlation')[['source', 'lag_hours', 'correlation']]
    axes[1].barh(range(len(top_by_lag)), top_by_lag['correlation'].values, color='steelblue')
    axes[1].set_yticks(range(len(top_by_lag)))
    axes[1].set_yticklabels([f"{row['source']} (lag {int(row['lag_hours'])}h)" 
                               for _, row in top_by_lag.iterrows()])
    axes[1].set_xlabel('Correlation')
    axes[1].set_title('Top 10 Predictive Signals (by correlation strength)')
    axes[1].grid(axis='x', alpha=0.3)
    
    plt.tight_layout()
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    heatmap_path = ANALYSIS_DIR / "correlation_heatmap.png"
    plt.savefig(heatmap_path, dpi=150)
    print(f"Saved correlation heatmap to {heatmap_path}")
    plt.close()

if __name__ == "__main__":
    print("="*60)
    print("Correlation & Lead/Lag Analysis")
    print("="*60)
    
    # Load all data sources
    ng_hourly = load_ng_tick_data()
    eia_data = load_eia_data()
    fred_data = load_fred_data()
    lmp_data = load_grid_lmp_data()
    
    if len(ng_hourly) == 0:
        print("Error: No NG data available. Exiting.")
        exit(1)
    
    # Align all to NG index (hourly)
    sources = {}
    if len(eia_data) > 0:
        sources['EIA_Storage'] = eia_data['storage_bcf'].resample('1h').ffill()
    if len(fred_data) > 0:
        sources['FRED'] = fred_data
    if len(lmp_data) > 0:
        sources['Grid_LMP'] = lmp_data['lmp']
    
    # Compute correlations
    print("\nComputing lead/lag correlations...")
    corr_df = compute_correlations(ng_hourly['log_returns'], sources)

    if corr_df.empty:
        corr_df = pd.DataFrame(columns=['source', 'lag_hours', 'correlation', 'n_samples'])
        print("No correlations computed (insufficient overlapping samples).")
    
    # Save results
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = ANALYSIS_DIR / "correlation_analysis.csv"
    corr_df.to_csv(csv_path, index=False)
    print(f"\nSaved {len(corr_df)} correlation results to {csv_path}")
    
    # Print top signals
    if len(corr_df) > 0:
        print("\nTop Predictive Signals (by |correlation|):")
        print(corr_df.reindex(corr_df['correlation'].abs().sort_values(ascending=False).index).head(15).to_string())
        visualize_correlations(corr_df)
    else:
        print("\nNo signals to display or plot.")
    
    print("\n" + "="*60)
    print("Analysis complete. Review analysis/correlation_analysis.csv and PNG")
    print("="*60)
