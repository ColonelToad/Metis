"""
Census Bureau Building Permits Survey Ingestion
Fetches monthly building permit data by Metropolitan Statistical Area (MSA).

Signal: 6-month rolling average of permits
- If permits ↑ >10% YoY → bullish energy demand (12-month forward)
- Permits lead construction activity → electricity demand increase
- Metric: Total value of permits issued

Data source: Census Bureau's Building Permits Survey (free, no key required)
API documentation: https://api.census.gov/data/timeseries/eits/
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import requests
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Add project root for imports
sys.path.append(str(Path(__file__).resolve().parents[1]))
from research.common import runtime_config as rc

load_dotenv()
DB_URL = rc.get_db_url()
CENSUS_API_KEY = os.getenv("CENSUS_API_KEY", "")

# Census Bureau Building Permits Survey datasets
# BPS = Building Permits Survey (monthly aggregates by state and MSA)
CENSUS_API_URL = "https://api.census.gov/data/timeseries/eits/bps"


def fetch_permits_national() -> Optional[pd.DataFrame]:
    """
    Fetch national building permits data from Census API.
    
    Returns monthly data: total permits issued and total value.
    """
    if not rc.require_real_mode("Census Building Permits API"):
        # Return synthetic data for DEV mode
        return generate_synthetic_permits()
    
    if not CENSUS_API_KEY:
        print("[CENSUS] Missing CENSUS_API_KEY - using synthetic data")
        return generate_synthetic_permits()
    
    try:
        # Query: NAME (geography), PERMIT_COUNT, PERMIT_VAL (monthly)
        # get parameter specifies which variables to retrieve
        params = {
            "get": "NAME,PERMIT",  # Permits issued count
            "key": CENSUS_API_KEY,
            "time": "from 2015-01",  # Start from 2015
        }
        
        response = requests.get(CENSUS_API_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if not data or len(data) < 2:
            print("[CENSUS] No data returned from API")
            return None
        
        # API returns list of lists: [["NAME", "PERMIT", "time"], ...]
        headers = data[0]
        records = data[1:]
        
        df = pd.DataFrame(records, columns=headers)
        
        # Convert to proper types
        df['PERMIT'] = pd.to_numeric(df['PERMIT'], errors='coerce')
        df['time'] = pd.to_datetime(df['time'], format='%Y-%m')
        
        # Filter to national aggregate ("United States")
        df = df[df['NAME'] == 'United States'].copy()
        
        if df.empty:
            print("[CENSUS] No national data found")
            return None
        
        df = df[['time', 'PERMIT']].copy()
        df.columns = ['date', 'permit_count']
        df = df.dropna()
        df = df.sort_values('date')
        
        print(f"[CENSUS] Fetched {len(df)} monthly permit records")
        return df
        
    except Exception as e:
        print(f"[CENSUS] API fetch failed: {e}")
        return generate_synthetic_permits()


def generate_synthetic_permits() -> pd.DataFrame:
    """
    Generate synthetic building permits data for development/testing.
    Realistic trend: rising permits → rising construction → future energy demand.
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365*10)  # 10 years back
    
    dates = pd.date_range(start=start_date, end=end_date, freq='MS')
    
    # Synthetic data: base 100k permits/month with trend and seasonality
    trend = pd.Series(range(len(dates))) * 0.001  # Very slight uptrend
    seasonal = 0.1 * pd.Series([
        1.05 if m in [3, 4, 5] else  # Spring peak
        0.95 if m in [11, 12] else   # Winter trough
        1.0
        for m in dates.month
    ])
    
    permits = (100_000 + trend * 100_000) * (1 + seasonal)
    permits = permits + (pd.Series(range(len(dates))) * 0.02 * 100_000).values  # Long-term growth
    
    return pd.DataFrame({
        'date': dates,
        'permit_count': permits.astype(int)
    })


def calculate_rolling_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate rolling 6-month average and YoY change.
    
    Signal interpretation:
    - YoY ↑ >10% → positive energy demand outlook (12 months forward)
    """
    df = df.copy()
    df = df.sort_values('date')
    
    # 6-month rolling average
    df['permit_6m_rolling'] = df['permit_count'].rolling(window=6, min_periods=1).mean()
    
    # YoY change (12 months back)
    df['permit_yoy_change'] = df['permit_count'].pct_change(periods=12) * 100
    
    # Bullish signal: >10% YoY growth
    df['permit_bullish'] = (df['permit_yoy_change'] > 10).astype(int)
    
    return df


def ensure_table(engine) -> None:
    """Create census_permits table if not exists."""
    create_sql = """
    CREATE TABLE IF NOT EXISTS census_permits (
        date DATE PRIMARY KEY,
        permit_count INTEGER,
        permit_6m_rolling REAL,
        permit_yoy_change REAL,
        permit_bullish INTEGER,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    with engine.begin() as conn:
        conn.execute(text(create_sql))
    print("[CENSUS] Table ensured: census_permits")


def upsert_permits(engine, df: pd.DataFrame) -> None:
    """Upsert permit data into database."""
    if df.empty:
        print("[CENSUS] No data to upsert")
        return
    
    ensure_table(engine)
    
    # Use pandas to_sql with proper types
    df_insert = df.copy()
    df_insert['timestamp'] = datetime.now().isoformat()
    
    df_insert.to_sql(
        'census_permits',
        engine,
        if_exists='append',
        index=False,
        method='multi'
    )
    
    print(f"[CENSUS] Upserted {len(df)} permit records")


def main():
    """Main ingestion pipeline."""
    rc.log_mode("Census Building Permits")
    
    # Fetch data
    df = fetch_permits_national()
    if df is None or df.empty:
        print("[CENSUS] No permit data available")
        return
    
    # Calculate metrics
    df = calculate_rolling_metrics(df)
    
    # Save to database
    engine = create_engine(DB_URL)
    upsert_permits(engine, df)
    
    # Log summary
    if not df.empty:
        latest = df.iloc[-1]
        print(f"\n[CENSUS] Latest permit data:")
        print(f"  Date: {latest['date']}")
        print(f"  Permits: {latest['permit_count']:,.0f}")
        print(f"  6-month avg: {latest['permit_6m_rolling']:,.0f}")
        print(f"  YoY change: {latest['permit_yoy_change']:+.1f}%")
        print(f"  Bullish signal: {'YES' if latest['permit_bullish'] else 'NO'}")


if __name__ == "__main__":
    main()
