#!/usr/bin/env python3
"""
Backfill historical data for FRED and EIA with proper column naming
Run this before feature engineering
"""
import os
import sys
from pathlib import Path
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import time

sys.path.append(str(Path(__file__).resolve().parents[1]))
from research.common import runtime_config as rc

load_dotenv()
FRED_API_KEY = os.getenv("FRED_API_KEY")
EIA_API_KEY = os.getenv("EIA_API_KEY")
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")

# FRED series to fetch
FRED_SERIES = {
    'UNRATE': 'unemployment_rate',
    'CPIENGSL': 'cpi_energy',
    'GASREGW': 'retail_gas_price',
    'DCOILWTICO': 'wti_crude_price',
    'INDPRO': 'industrial_production',
    'HOUST': 'housing_starts',
    'PCE': 'personal_consumption',
}

def fetch_fred_backfill(start_date='2015-01-01'):
    """Fetch FRED data from 2015 to present"""
    print(f"\n[FRED] Fetching {len(FRED_SERIES)} series from {start_date}...")
    
    engine = create_engine(DB_URL)
    all_data = []
    
    for series_id, col_name in FRED_SERIES.items():
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            'series_id': series_id,
            'api_key': FRED_API_KEY,
            'file_type': 'json',
            'observation_start': start_date
        }
        
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            if 'observations' in data:
                df = pd.DataFrame(data['observations'])
                df['date'] = pd.to_datetime(df['date'])  # Use 'date' not 'timestamp'
                df[col_name] = pd.to_numeric(df['value'], errors='coerce')
                df = df[['date', col_name]].dropna()
                
                all_data.append(df)
                print(f"  ✓ {series_id}: {len(df)} records")
        
        except Exception as e:
            print(f"  ✗ {series_id}: {e}")
        
        time.sleep(0.5)  # Rate limit
    
    # Merge all series on date
    if all_data:
        merged = all_data[0]
        for df in all_data[1:]:
            merged = merged.merge(df, on='date', how='outer')
        
        merged = merged.sort_values('date')
        
        print(f"\n[FRED] Merged dataset: {len(merged)} rows, {merged['date'].min()} to {merged['date'].max()}")
        
        # Save to database (replace existing)
        with engine.connect() as conn:
            # Drop old table if exists
            conn.execute(text("DROP TABLE IF EXISTS fred_macro"))
            conn.commit()
        
        merged.to_sql('fred_macro', engine, if_exists='replace', index=False)
        print("[FRED] ✓ Saved to database")

def fetch_eia_backfill():
    """Fetch EIA storage data from 2015 to present"""
    print(f"\n[EIA] Fetching natural gas storage data...")
    
    engine = create_engine(DB_URL)
    
    try:
        # EIA storage API
        url = "https://api.eia.gov/v2/natural-gas/stor/wkly/data/"
        params = {
            "api_key": EIA_API_KEY,
            "frequency": "weekly",
            "data[0]": "value",
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            "length": 5000
        }
        
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        df = pd.DataFrame(data['response']['data'])
        df['date'] = pd.to_datetime(df['period'])  # Use 'date' not 'timestamp'
        df['storage_bcf'] = pd.to_numeric(df['value'], errors='coerce')
        df = df[['date', 'storage_bcf']].dropna()
        df = df.sort_values('date')
        
        print(f"[EIA] Storage: {len(df)} records, {df['date'].min()} to {df['date'].max()}")
        
        # Save to database
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE IF EXISTS eia_storage"))
            conn.commit()
        
        df.to_sql('eia_storage', engine, if_exists='replace', index=False)
        print("[EIA] ✓ Storage saved")
        
    except Exception as e:
        print(f"[EIA] Storage error: {e}")
    
    try:
        # EIA production API
        url = "https://api.eia.gov/v2/natural-gas/prod/sum/data/"
        params = {
            "api_key": EIA_API_KEY,
            "frequency": "monthly",
            "data[0]": "value",
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            "length": 1000
        }
        
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        df = pd.DataFrame(data['response']['data'])
        df['date'] = pd.to_datetime(df['period'])  # Use 'date' not 'timestamp'
        df['production_mmcf'] = pd.to_numeric(df['value'], errors='coerce')
        df = df[['date', 'production_mmcf']].dropna()
        df = df.sort_values('date')
        
        print(f"[EIA] Production: {len(df)} records, {df['date'].min()} to {df['date'].max()}")
        
        # Save to database
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE IF EXISTS eia_production"))
            conn.commit()
        
        df.to_sql('eia_production', engine, if_exists='replace', index=False)
        print("[EIA] ✓ Production saved")
        
    except Exception as e:
        print(f"[EIA] Production error: {e}")

def main():
    print("="*80)
    print("BACKFILLING HISTORICAL DATA (2015 - Present)")
    print("="*80)
    
    if not FRED_API_KEY:
        print("❌ FRED_API_KEY not set in .env")
    else:
        fetch_fred_backfill(start_date='2015-01-01')
    
    if not EIA_API_KEY:
        print("❌ EIA_API_KEY not set in .env")
    else:
        fetch_eia_backfill()
    
    print("\n" + "="*80)
    print("BACKFILL COMPLETE")
    print("="*80)
    print("\nNext steps:")
    print("1. Run engineer_features.py to regenerate feature CSVs")
    print("2. Re-run the LSTM notebook")

if __name__ == "__main__":
    main()
