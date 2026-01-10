"""
CME Natural Gas Futures Historical Data Ingestion
Fetches daily OHLCV data from Yahoo Finance (NGF=F)
Date range: Aug 30, 2000 to Jan 9, 2026
No API key required - public data
"""
import os
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import yfinance as yf

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
METIS_MODE = os.getenv("METIS_MODE", "DEV")


def require_real_mode(source: str) -> bool:
    if METIS_MODE != "REAL":
        print(f"[DEV MODE] Skipping {source}")
        return False
    return True


def get_ng_futures_historical(
    start_date: str = "2000-08-30",
    end_date: str = "2026-01-09"
) -> pd.DataFrame:
    """
    Fetch historical NG futures data from Yahoo Finance
    
    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
    
    Returns:
        DataFrame with columns: Date, Open, High, Low, Close, Volume, Adj Close
    """
    if not require_real_mode("NG Futures Historical"):
        return pd.DataFrame()
    
    print(f"[REAL] Fetching NG futures (NG=F) from {start_date} to {end_date}")
    
    try:
        # Fetch data from Yahoo Finance
        data = yf.download("NG=F", start=start_date, end=end_date, progress=False)
        
        if data.empty:
            print("No data returned from Yahoo Finance")
            return pd.DataFrame()
        
        # Reset index to make Date a column
        data = data.reset_index()
        # Normalize column names (handle MultiIndex columns)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [col[0].lower() if isinstance(col, tuple) else col.lower() for col in data.columns]
        else:
            data.columns = [col.lower() for col in data.columns]
        
        # Print columns for debugging
        print(f"Columns: {list(data.columns)}")
        
        print(f"Fetched {len(data)} daily records")
        return data
    
    except Exception as e:
        print(f"Error fetching NG futures data: {e}")
        return pd.DataFrame()


def normalize_and_save(df: pd.DataFrame) -> int:
    """
    Normalize data and upsert to ng_futures_daily table
    
    Args:
        df: DataFrame with columns from Yahoo Finance
    
    Returns:
        Number of records upserted
    """
    if df.empty:
        print("No data to save")
        return 0
    # Columns are already lowercase: date, open, high, low, close, volume
    # Ensure date is datetime
    df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
    
    # Add timestamp column (current time)
    now = datetime.utcnow()
    df['timestamp'] = now
    
    # Type conversion and NaN handling
    records = []
    for _, row in df.iterrows():
        try:
            record = {
                'date': row['date'].to_pydatetime() if hasattr(row['date'], 'to_pydatetime') else row['date'],
                'open': float(row['open']) if pd.notna(row['open']) else None,
                'high': float(row['high']) if pd.notna(row['high']) else None,
                'low': float(row['low']) if pd.notna(row['low']) else None,
                'close': float(row['close']) if pd.notna(row['close']) else None,
                'volume': int(row['volume']) if pd.notna(row['volume']) else 0,
                'timestamp': now
            }
            records.append(record)
        except Exception as e:
            print(f"Error processing row {row['date']}: {e}")
            continue
    
    if not records:
        print("No valid records to save")
        return 0
    
    # Connect to database
    engine = create_engine(DB_URL)
    
    try:
        # Upsert with SQLite ON CONFLICT
        with engine.connect() as conn:
            # Delete old records before insert (fresh load)
            conn.execute(text("DELETE FROM ng_futures_daily"))
            
            # Insert new records
            insert_sql = """
            INSERT INTO ng_futures_daily 
            (date, open, high, low, close, volume, timestamp)
            VALUES (:date, :open, :high, :low, :close, :volume, :timestamp)
            ON CONFLICT(date) DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                timestamp = EXCLUDED.timestamp
            """
            
            for record in records:
                conn.execute(text(insert_sql), record)
            
            conn.commit()
        
        print(f"Upserted {len(records)} records to ng_futures_daily")
        return len(records)
    
    except Exception as e:
        print(f"Error saving to database: {e}")
        return 0


if __name__ == "__main__":
    # Fetch historical data
    df = get_ng_futures_historical()
    
    if not df.empty:
        # Save to database
        saved_count = normalize_and_save(df)
        print(f"\n[SUCCESS] Saved {saved_count} records")
    else:
        print("[FAILED] No data fetched")
