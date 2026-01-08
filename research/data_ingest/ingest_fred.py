"""
FRED Macro Indicators Ingestion
Fetches relevant macro series for energy markets
"""
import os
import sys
from pathlib import Path
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine
import time

# Add project root for imports
sys.path.append(str(Path(__file__).resolve().parents[1]))
from research.common import runtime_config as rc

load_dotenv()
FRED_API_KEY = os.getenv("FRED_API_KEY")
DB_URL = rc.get_db_url()

# Relevant macro series for natural gas trading
SERIES_IDS = {
    'UNRATE': 'unemployment_rate',
    'CPIENGSL': 'cpi_energy',
    'GASREGW': 'retail_gas_price',
    'DCOILWTICO': 'wti_crude_price',
    'INDPRO': 'industrial_production',
    'HOUST': 'housing_starts',
    'PCE': 'personal_consumption',
}

def fetch_fred_series(series_id, start_date, max_retries=3):
    """Fetch a single FRED series with retry logic"""
    if not rc.require_real_mode(f"FRED {series_id}"):
        return pd.DataFrame()
    
    url = f"https://api.stlouisfed.org/fred/series/observations"
    params = {
        'series_id': series_id,
        'api_key': FRED_API_KEY,
        'file_type': 'json',
        'observation_start': start_date.strftime('%Y-%m-%d')
    }
    
    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            df = pd.DataFrame(data['observations'])
            df['timestamp'] = pd.to_datetime(df['date'])
            df['value'] = pd.to_numeric(df['value'], errors='coerce')
            
            return df[['timestamp', 'value']]
        
        except requests.exceptions.HTTPError as e:
            if e.response.status_code >= 500:
                # Server error - retry with exponential backoff
                wait_time = 2 ** attempt  # 1s, 2s, 4s
                print(f"FRED server error for {series_id} (attempt {attempt + 1}/{max_retries}). Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                # Client error (4xx) - don't retry
                print(f"FRED client error for {series_id}: {e}")
                return pd.DataFrame()
        
        except Exception as e:
            print(f"Failed to fetch {series_id}: {e}")
            return pd.DataFrame()
    
    print(f"Failed to fetch {series_id} after {max_retries} attempts")
    return pd.DataFrame()

if __name__ == "__main__":
    rc.log_mode("FRED")
    # Fetch 2 years of data
    start_date = datetime.now() - timedelta(days=730)
    
    print("Fetching FRED macro indicators...")
    
    all_data = []
    
    for series_id, column_name in SERIES_IDS.items():
        try:
            df = fetch_fred_series(series_id, start_date)
            df = df.rename(columns={'value': column_name})
            df['series_id'] = series_id
            all_data.append(df)
            print(f"Fetched {len(df)} observations for {series_id}")
        except Exception as e:
            print(f"Failed to fetch {series_id}: {e}")
    
    if all_data:
        combined_df = pd.concat(all_data, ignore_index=True)
        
        # Save to database
        engine = create_engine(DB_URL)
        combined_df.to_sql('fred_macro', engine, if_exists='replace', index=False)
        
        print(f"Saved {len(combined_df)} total macro observations to database")
