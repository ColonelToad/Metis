"""
Congressional Trading Data Ingestion
Fetches recent congressional stock trades from Finnhub
"""
import os
import sys
from pathlib import Path
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine

# Add project root for imports
sys.path.append(str(Path(__file__).resolve().parents[1]))
from research.common import runtime_config as rc

load_dotenv()
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
DB_URL = rc.get_db_url()

def fetch_congress_trades():
    """Fetch recent congressional trades from Finnhub"""
    if not rc.require_real_mode("Congressional trades API"):
        return pd.DataFrame()
    url = "https://finnhub.io/api/v1/stock/congressional-trading"
    params = {
        'token': FINNHUB_API_KEY,
    }
    
    response = requests.get(url, params=params)
    response.raise_for_status()
    
    data = response.json()
    df = pd.DataFrame(data['data'])
    
    if len(df) > 0:
        df['timestamp'] = pd.to_datetime(df['transactionDate'])
        
        # Filter for energy-related symbols
        energy_symbols = ['XLE', 'XOP', 'OIH', 'UNG', 'BOIL', 'KOLD', 'FCG']
        df_energy = df[df['symbol'].isin(energy_symbols)]
        
        return df[['timestamp', 'name', 'symbol', 'transactionType', 'amount', 'representative']]
    
    return pd.DataFrame()

if __name__ == "__main__":
    rc.log_mode("Congress Trades")
    print("Fetching congressional trading data...")
    
    df = fetch_congress_trades()
    
    if len(df) > 0:
        print(f"Fetched {len(df)} congressional trades")
        
        # Save to database
        engine = create_engine(DB_URL)
        df.to_sql('congress_trades', engine, if_exists='replace', index=False)
        
        print("Congressional trades saved to database")
    else:
        print("No congressional trades fetched")
