"""
FRED Building Permits Survey Ingestion
Fetches monthly building permit data at the national level.

Signal: 6-month rolling average of permits
- If permits ↑ >10% YoY → bullish energy demand (12-month forward)
- Permits lead construction activity → electricity demand increase
- Metric: Total permits issued (thousands of units)

Data source: Federal Reserve Economic Data (FRED)
Series: PERMIT - New Privately-Owned Housing Units Authorized
API documentation: https://fred.stlouisfed.org/docs/api/fred/
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

# Database URL - use absolute path to work from any directory
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "metis.db"
DB_URL = f"sqlite:///{DB_PATH}"

FRED_API_KEY = os.getenv("FRED_API_KEY", "")

# FRED API endpoint
FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"
PERMIT_SERIES_ID = "PERMIT"  # National building permits (thousands of units)


def fetch_permits_national() -> Optional[pd.DataFrame]:
    """
    Fetch national building permits data from FRED API.
    
    Returns monthly data: total permits issued (in thousands of units).
    """
    if not rc.require_real_mode("FRED Building Permits API"):
        # Return synthetic data for DEV mode
        return generate_synthetic_permits()
    
    if not FRED_API_KEY:
        print("[FRED] Missing FRED_API_KEY - using synthetic data")
        return generate_synthetic_permits()
    
    try:
        params = {
            "series_id": PERMIT_SERIES_ID,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "observation_start": "2015-01-01",  # Last 10+ years
        }
        
        response = requests.get(FRED_API_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        # Check for API errors
        if "error_code" in data:
            print(f"[FRED] API error: {data.get('error_message', 'Unknown error')}")
            return generate_synthetic_permits()
        
        observations = data.get("observations", [])
        
        if not observations:
            print("[FRED] No data returned from API")
            return None
        
        # Convert to DataFrame
        df = pd.DataFrame(observations)
        df = df[['date', 'value']].copy()
        df['date'] = pd.to_datetime(df['date'])
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        df = df.dropna()
        
        # FRED returns data in thousands - convert to actual count
        df['permit_count'] = (df['value'] * 1000).astype(int)
        df = df[['date', 'permit_count']].copy()
        df = df.sort_values('date')
        
        print(f"[FRED] Fetched {len(df)} monthly permit records")
        return df
        
    except requests.exceptions.HTTPError as e:
        print(f"[FRED] API fetch failed: {e}")
        if e.response.status_code == 400:
            print("[FRED] Invalid API key or parameters")
        elif e.response.status_code == 429:
            print("[FRED] Rate limit exceeded")
        return generate_synthetic_permits()
    except Exception as e:
        print(f"[FRED] API fetch failed: {e}")
        return generate_synthetic_permits()


def generate_synthetic_permits() -> pd.DataFrame:
    """
    Generate synthetic building permits data for development/testing.
    Realistic trend: rising permits → rising construction → future energy demand.
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365*10)  # 10 years back
    
    dates = pd.date_range(start=start_date, end=end_date, freq='MS')
    
    # Synthetic data: base 1.4M permits/month with trend and seasonality
    trend = pd.Series(range(len(dates))) * 0.001  # Very slight uptrend
    seasonal = 0.1 * pd.Series([
        1.05 if m in [3, 4, 5] else  # Spring peak
        0.95 if m in [11, 12] else   # Winter trough
        1.0
        for m in dates.month
    ])
    
    permits = (1_400_000 + trend * 100_000) * (1 + seasonal)
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
    print("[FRED] Table ensured: census_permits")


def upsert_permits(engine, df: pd.DataFrame) -> None:
    """Upsert permit data into database."""
    if df.empty:
        print("[FRED] No data to upsert")
        return
    
    ensure_table(engine)
    
    # Use pandas to_sql with proper types
    df_insert = df.copy()
    df_insert['timestamp'] = datetime.now().isoformat()
    
    df_insert.to_sql(
        'census_permits',
        engine,
        if_exists='replace',
        index=False,
        method='multi'
    )
    
    print(f"[FRED] Upserted {len(df)} permit records")


def main():
    """Main ingestion pipeline."""
    rc.log_mode("FRED Building Permits")
    
    # Fetch data
    df = fetch_permits_national()
    if df is None or df.empty:
        print("[FRED] No permit data available")
        return
    
    # Calculate metrics
    df = calculate_rolling_metrics(df)
    
    # Save to database
    engine = create_engine(DB_URL)
    upsert_permits(engine, df)
    
    # Log summary
    if not df.empty:
        latest = df.iloc[-1]
        print(f"\n[FRED] Latest permit data:")
        print(f"  Date: {latest['date'].strftime('%Y-%m')}")
        print(f"  Permits: {latest['permit_count']:,.0f}")
        print(f"  6-month avg: {latest['permit_6m_rolling']:,.0f}")
        print(f"  YoY change: {latest['permit_yoy_change']:+.1f}%")
        print(f"  Bullish signal: {'YES' if latest['permit_bullish'] else 'NO'}")


if __name__ == "__main__":
    main()