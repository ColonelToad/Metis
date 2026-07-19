"""
EIA Natural Gas Storage and Production Data Ingestion
Fetches weekly storage reports and production data
"""
import os
import sys
from pathlib import Path
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine

# Add parent directory (research/) to Python path if not already there
parent_dir = str(Path(__file__).parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from common import runtime_config as rc

load_dotenv()
EIA_API_KEY = os.getenv("EIA_API_KEY")
DB_URL = rc.get_db_url()

def fetch_ng_storage():
    """Fetch weekly natural gas storage data"""
    if not rc.require_real_mode("EIA storage API"):
        return pd.DataFrame()
    url = f"https://api.eia.gov/v2/natural-gas/stor/wkly/data/"
    params = {
        "api_key": EIA_API_KEY,
        "frequency": "weekly",
        "data[0]": "value",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 5000
    }
    
    response = requests.get(url, params=params)
    response.raise_for_status()
    
    data = response.json()
    df = pd.DataFrame(data['response']['data'])
    df['timestamp'] = pd.to_datetime(df['period'])
    df = df.rename(columns={'value': 'storage_bcf'})
    print(f"[EIA storage] distinct duoarea values in response: {sorted(df['duoarea'].unique()) if 'duoarea' in df.columns else 'duoarea column not present'}")
    if 'duoarea' in df.columns:
        df = df[df['duoarea'] == 'R48']  # R48 = Lower 48 States total (storage endpoint's own
        # region scheme -- R31-R35 are the five sub-national regions, distinct from the 'NUS'
        # code used by the production endpoint. Confirmed via live response: distinct duoarea
        # values were ['R31','R32','R33','R34','R35','R48'] -- no 'NUS' code exists here at all.
        print(f"[EIA storage] Filtered to USA aggregate (duoarea=='R48'): {len(df)} records")
    else:
        print("[EIA storage] WARNING: no duoarea column in response -- cannot filter to national "
            "aggregate. Falling back to unfiltered data; do not trust row count/labels downstream "
            "until this is investigated.")
    
    return df[['timestamp', 'storage_bcf', 'area-name']]

def fetch_ng_production():
    """Fetch natural gas production data (USA aggregate only)"""
    if not rc.require_real_mode("EIA production API"):
        return pd.DataFrame()
    url = f"https://api.eia.gov/v2/natural-gas/prod/sum/data/"
    params = {
        "api_key": EIA_API_KEY,
        "frequency": "monthly",
        "data[0]": "value",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 1000
    }
    
    response = requests.get(url, params=params)
    response.raise_for_status()
    
    data = response.json()
    df = pd.DataFrame(data['response']['data'])
    df['timestamp'] = pd.to_datetime(df['period'])
    df = df.rename(columns={'value': 'production_mmcf'})
    
    # Filter to USA aggregate only (many regional series have sparse/missing data)
    # This removes ~80% of rows that are mostly NULL
    print(f"[EIA production] response columns: {list(df.columns)}")
    if 'duoarea' in df.columns and 'process' in df.columns and 'process-name' in df.columns:
        nus_rows = df[df['duoarea'] == 'NUS']
        #pairs = nus_rows[['process', 'process-name', 'production_mmcf']].drop_duplicates(subset=['process','process-name']).sort_values('period') if 'period' in nus_rows.columns else nus_rows[['process','process-name','production_mmcf']].drop_duplicates(subset=['process','process-name'])
        pairs = (nus_rows.sort_values('period')[['process', 'process-name', 'production_mmcf']]
         .drop_duplicates(subset=['process','process-name'])) if 'period' in nus_rows.columns else (nus_rows[['process','process-name','production_mmcf']]
         .drop_duplicates(subset=['process','process-name']))
        print(f"[EIA production] NUS-level (process, process-name, sample value) pairs:")
        for _, r in pairs.iterrows():
            print(f"    {r['process']:6s} -> {r['process-name']:35s} sample_value={r['production_mmcf']}")
    if 'duoarea' in df.columns:
        df = df[df['duoarea'] == 'NUS']  # 'NUS' = National US aggregate, not 'USA'
    
    # Drop rows with NULL production values
    df = df.dropna(subset=['production_mmcf'])
    
    print(f"Filtered production data to {len(df)} USA aggregate records")
    
    return df[['timestamp', 'production_mmcf', 'area-name']]

def main():
    """Main entry point for EIA data ingestion"""
    rc.log_mode("EIA")
    print("Fetching EIA natural gas data...")
    
    storage_df = fetch_ng_storage()
    if len(storage_df) > 0:
        print(f"Fetched {len(storage_df)} storage records")
    
    production_df = fetch_ng_production()
    if len(production_df) > 0:
        print(f"Fetched {len(production_df)} production records")
    
    # Save to database only if we have real data
    if len(storage_df) > 0 or len(production_df) > 0:
        engine = create_engine(DB_URL)
        if len(storage_df) > 0:
            storage_df.to_sql('eia_storage', engine, if_exists='replace', index=False)
        if len(production_df) > 0:
            production_df.to_sql('eia_production', engine, if_exists='replace', index=False)
        print("EIA data saved to database")
    else:
        print("No EIA data fetched (DEV mode or API unavailable)")

if __name__ == "__main__":
    main()
