"""
Stock Market Data Ingestion using Stooq
Fetches historical stock data for energy companies and related equities
"""
import os
import sys
from pathlib import Path
import pandas as pd
import pandas_datareader.data as web
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from dotenv import load_dotenv

# Add project root for imports
sys.path.append(str(Path(__file__).resolve().parents[1]))
from research.common import runtime_config as rc

load_dotenv()
DB_URL = rc.get_db_url()

# Energy-related stocks (natural gas, LNG, pipelines, utilities)
ENERGY_TICKERS = {
    # Natural Gas & LNG
    'CHK': 'Chesapeake Energy',
    'EQT': 'EQT Corporation',
    'AR': 'Antero Resources',
    'CNX': 'CNX Resources',
    'RRC': 'Range Resources',
    
    # Pipelines & Midstream
    'KMI': 'Kinder Morgan',
    'WMB': 'Williams Companies',
    'EPD': 'Enterprise Products',
    'ET': 'Energy Transfer',
    'OKE': 'ONEOK',
    
    # Utilities with Gas Exposure
    'NEE': 'NextEra Energy',
    'D': 'Dominion Energy',
    'SO': 'Southern Company',
    'DUK': 'Duke Energy',
    
    # ETFs
    'XLE': 'Energy Select Sector',
    'UNG': 'US Natural Gas Fund',
    'FCG': 'First Trust Natural Gas ETF',
    'XOP': 'SPDR S&P Oil & Gas',
}

def fetch_stock_data(ticker, start_date, end_date):
    """Fetch historical stock data from Stooq"""
    if not rc.require_real_mode(f"Stooq {ticker}"):
        return pd.DataFrame()
    
    try:
        df = web.DataReader(ticker, 'stooq', start_date, end_date)
        
        # Stooq returns descending order; reverse it
        df = df.sort_index()
        
        # Add ticker column
        df['ticker'] = ticker
        df['timestamp'] = df.index
        
        # Standardize column names
        df = df.rename(columns={
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'volume'
        })
        
        return df[['timestamp', 'ticker', 'open', 'high', 'low', 'close', 'volume']]
    
    except Exception as e:
        print(f"Failed to fetch {ticker}: {e}")
        return pd.DataFrame()

if __name__ == "__main__":
    rc.log_mode("Stooq Stock Data")
    
    # Fetch 2 years of historical data
    end_date = datetime.now()
    start_date = end_date - timedelta(days=730)
    
    print(f"Fetching stock data from Stooq ({start_date.date()} to {end_date.date()})...")
    
    all_data = []
    
    for ticker, company in ENERGY_TICKERS.items():
        df = fetch_stock_data(ticker, start_date, end_date)
        if not df.empty:
            df['company_name'] = company
            all_data.append(df)
            print(f"Fetched {len(df)} records for {ticker} ({company})")
    
    if all_data:
        combined_df = pd.concat(all_data, ignore_index=True)
        
        # Save to database
        engine = create_engine(DB_URL)
        combined_df.to_sql('stock_prices', engine, if_exists='replace', index=False)
        
        print(f"Saved {len(combined_df)} total stock records to database")
        
        # Summary stats
        print(f"\nData range: {combined_df['timestamp'].min()} to {combined_df['timestamp'].max()}")
        print(f"Tickers collected: {combined_df['ticker'].nunique()}")
    else:
        print("No stock data fetched")
