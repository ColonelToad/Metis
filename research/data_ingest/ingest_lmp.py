"""
Grid LMP Data Ingestion using gridstatus
Fetches real-time and day-ahead LMP for CAISO
Includes file-based caching to avoid slow re-fetches
"""
import os
import sys
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta
from gridstatus import CAISO
from sqlalchemy import create_engine
from dotenv import load_dotenv
import hashlib

# Add project root for imports
sys.path.append(str(Path(__file__).resolve().parents[1]))
from research.common import runtime_config as rc

load_dotenv()
DB_URL = rc.get_db_url()

# Cache directory
CACHE_DIR = Path("data/cache/lmp")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def get_cache_key(start_date, end_date, market="REAL_TIME_5_MIN"):
    """Generate cache filename based on query params"""
    key_str = f"caiso_{start_date.date()}_{end_date.date()}_{market}"
    return f"{key_str}.parquet"

def fetch_caiso_lmp(start_date, end_date, use_cache=True):
    """
    Fetch CAISO real-time LMP data with optional caching
    Cache is stored as Parquet files keyed by date range
    """
    if not rc.require_real_mode("CAISO LMP API"):
        return pd.DataFrame()
    
    # Check cache first
    cache_file = CACHE_DIR / get_cache_key(start_date, end_date)
    if use_cache and cache_file.exists():
        print(f"Loading from cache: {cache_file.name}")
        return pd.read_parquet(cache_file)
    
    # Fetch from API
    caiso = CAISO()
    df = caiso.get_lmp(
        date=start_date,
        end=end_date,
        market="REAL_TIME_5_MIN"
    )
    
    df['iso'] = 'CAISO'
    
    # Save to cache
    if not df.empty:
        df.to_parquet(cache_file)
        print(f"Cached to: {cache_file.name}")
    
    return df

if __name__ == "__main__":
    rc.log_mode("LMP")
    # Fetch last 7 days
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)
    
    print("Fetching LMP data from CAISO...")
    
    try:
        caiso_df = fetch_caiso_lmp(start_date, end_date)
        print(f"Fetched {len(caiso_df)} CAISO LMP records")
        
        if not caiso_df.empty:
            # Standardize columns
            caiso_df = caiso_df.rename(columns={
                'Time': 'timestamp',
                'LMP': 'lmp',
                'Location': 'node_id'
            })
            
            # Save to database
            engine = create_engine(DB_URL)
            caiso_df.to_sql('grid_lmp', engine, if_exists='append', index=False)
            
            print(f"Saved {len(caiso_df)} LMP records to database")
        else:
            print("No LMP data fetched")
    except Exception as e:
        print(f"CAISO fetch failed: {e}")
