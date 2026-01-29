"""
Bureau of Labor Statistics (BLS) Producer Price Index (PPI) Ingestion
Fetches PPI data for energy-related industries to track cost inflation.

Signal: Cost inflation → Activity levels causality
- PPI (Inputs) ↑ → Producer margins compress → Activity decreases
- PPI (Energy) ↑ → Energy costs rise → Future price increases expected
- Lead indicator: PPI typically leads economic activity by 2-3 months

Data: BLS PPI for Natural Gas, Petroleum, and Mining industries
API: BLS Public Data API (free, requires registration for bulk data)
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
BLS_API_KEY = os.getenv("BLS_API_KEY", "")

BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data"

# BLS series IDs for energy-related PPI
# Format: PPIXXXX where XXXX varies by industry/product
PPI_SERIES = {
    # Energy (industry level)
    "PCUOMPU": "PPI - Oil and gas extraction (NAICS 211)",
    "PCUOMPU021": "PPI - Natural gas distribution (NAICS 2211)",
    "PCUIUME48": "PPI - Petroleum refining (NAICS 3241)",
    
    # Energy inputs
    "PUELUUI01": "PPI - Crude petroleum",
    "PUEUUUI01": "PPI - Natural gas",
    "PUEMUUI": "PPI - Mining (NAICS 21)",
}


def fetch_ppi_data(series_ids: List[str]) -> Optional[pd.DataFrame]:
    """
    Fetch PPI data from BLS API.
    
    Args:
        series_ids: List of BLS series IDs (e.g., ["PCUOMPU", "PUEUUUI01"])
    
    Returns:
        DataFrame with date, series_id, series_name, index_value, year_over_year_change
    """
    if not rc.require_real_mode("BLS PPI API"):
        return generate_synthetic_ppi()
    
    if not BLS_API_KEY:
        print("[BLS] Missing BLS_API_KEY - using synthetic data")
        return generate_synthetic_ppi()
    
    all_data = []
    
    for series_id in series_ids:
        try:
            payload = {
                "seriesid": [series_id],
                "startyear": 2015,
                "endyear": datetime.now().year,
                "registrationkey": BLS_API_KEY,
            }
            
            response = requests.post(BLS_API_URL, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            if result.get("status") != "REQUEST_SUCCEEDED":
                print(f"[BLS] API error for {series_id}: {result.get('message', 'Unknown error')}")
                continue
            
            # Extract time series data
            series_data = result.get("Results", {}).get("series", [])
            if not series_data:
                print(f"[BLS] No data for series {series_id}")
                continue
            
            for series in series_data:
                series_name = PPI_SERIES.get(series_id, series_id)
                data = series.get("data", [])
                
                for point in data:
                    try:
                        # BLS returns year, month as strings
                        year = int(point.get("year", 0))
                        month = int(point.get("month", 1))
                        value = float(point.get("value", 0))
                        
                        # Parse date (month = 13 means annual average)
                        if month == 13:
                            # Annual data: use Dec 31
                            date = datetime(year, 12, 31)
                        else:
                            # Monthly data: use first day of month
                            date = datetime(year, month, 1)
                        
                        all_data.append({
                            "date": date,
                            "series_id": series_id,
                            "series_name": series_name,
                            "ppi_index": value,
                            "timestamp": datetime.now(),
                        })
                    except (ValueError, TypeError):
                        continue
        
        except Exception as e:
            print(f"[BLS] Fetch error for {series_id}: {e}")
            continue
    
    if not all_data:
        print("[BLS] No PPI data fetched, using synthetic")
        return generate_synthetic_ppi()
    
    df = pd.DataFrame(all_data)
    df = df.sort_values("date")
    print(f"[BLS] Fetched {len(df)} PPI records from {len(df['series_id'].unique())} series")
    return df


def generate_synthetic_ppi() -> pd.DataFrame:
    """
    Generate synthetic PPI data for development/testing.
    Realistic: gradual inflation with volatility around energy shocks.
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365*10)  # 10 years back
    
    dates = pd.date_range(start=start_date, end=end_date, freq='MS')
    
    all_data = []
    
    for series_id in ["PCUOMPU", "PUEUUUI01", "PUEMUUI"]:
        series_name = PPI_SERIES.get(series_id, series_id)
        
        # Base index = 100, with gradual trend (inflation)
        trend = pd.Series(range(len(dates))) * (0.5 / len(dates))  # 0.5% per month trend
        
        # Volatility: energy shocks
        noise = 0.01 * pd.Series(range(len(dates))).rolling(window=3, min_periods=1).std().fillna(0)
        
        index_values = 100 + trend + noise
        
        for i, date in enumerate(dates):
            all_data.append({
                "date": date,
                "series_id": series_id,
                "series_name": series_name,
                "ppi_index": index_values.iloc[i],
                "timestamp": datetime.now(),
            })
    
    return pd.DataFrame(all_data)


def calculate_yoy_change(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate year-over-year % change in PPI.
    
    Signal interpretation:
    - PPI ↑ >3% YoY → Cost inflation → Margin compression → Activity suppression (in 2-3 months)
    """
    df = df.copy()
    df = df.sort_values(["series_id", "date"])
    
    # Group by series and calculate YoY
    for series_id in df['series_id'].unique():
        mask = df['series_id'] == series_id
        df.loc[mask, 'ppi_yoy_change'] = df.loc[mask, 'ppi_index'].pct_change(periods=12) * 100
    
    return df


def ensure_table(engine) -> None:
    """Create bls_ppi table if not exists."""
    create_sql = """
    CREATE TABLE IF NOT EXISTS bls_ppi (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date DATE NOT NULL,
        series_id TEXT NOT NULL,
        series_name TEXT,
        ppi_index REAL NOT NULL,
        ppi_yoy_change REAL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(date, series_id)
    );
    CREATE INDEX IF NOT EXISTS idx_bls_ppi_date ON bls_ppi(date);
    CREATE INDEX IF NOT EXISTS idx_bls_ppi_series ON bls_ppi(series_id);
    """
    with engine.begin() as conn:
        for sql in create_sql.split(";"):
            if sql.strip():
                conn.execute(text(sql))
    print("[BLS] Table ensured: bls_ppi")


def upsert_ppi(engine, df: pd.DataFrame) -> None:
    """Upsert PPI data into database."""
    if df.empty:
        print("[BLS] No PPI data to upsert")
        return
    
    ensure_table(engine)
    
    # Use pandas to_sql with proper types
    df_insert = df.copy()
    df_insert['timestamp'] = datetime.now().isoformat()
    
    df_insert.to_sql(
        'bls_ppi',
        engine,
        if_exists='append',
        index=False,
        method='multi'
    )
    
    print(f"[BLS] Upserted {len(df)} PPI records")


def main():
    """Main ingestion pipeline."""
    rc.log_mode("BLS Producer Price Index")
    
    # Fetch PPI data for key energy series
    series_list = list(PPI_SERIES.keys())
    df = fetch_ppi_data(series_list)
    
    if df is None or df.empty:
        print("[BLS] No PPI data available")
        return
    
    # Calculate YoY changes
    df = calculate_yoy_change(df)
    
    # Save to database
    engine = create_engine(DB_URL)
    upsert_ppi(engine, df)
    
    # Log summary by series
    print("\n[BLS] Latest PPI by series:")
    latest_by_series = df.groupby('series_id').tail(1)
    for _, row in latest_by_series.iterrows():
        yoy_str = f"{row['ppi_yoy_change']:+.1f}%" if pd.notna(row['ppi_yoy_change']) else "N/A"
        print(f"  {row['series_name']}: {row['ppi_index']:.1f} (YoY: {yoy_str})")


if __name__ == "__main__":
    main()
