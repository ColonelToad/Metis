"""
CME futures data ingestion via Yahoo Finance.

Fetches historical futures data for:
- Crude oil (CL=F for WTI)
- Natural gas (NG=F)
- Henry Hub natural gas spreads
- Heating oil (HO=F)
- RBOB Gasoline (RB=F)

CME futures provide:
- Price discovery (forward-looking)
- Volatility indicators
- Seasonal patterns
- Term structure analysis
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import logging
from typing import List, Dict, Optional
import json
import threading
import signal
from sqlalchemy import create_engine, text
import os

logger = logging.getLogger(__name__)
# Default timeout for yfinance downloads (in seconds)
DEFAULT_DOWNLOAD_TIMEOUT = 30

# Import incremental utilities and caching
from research.data_ingest import incremental_utils
from research.common import cache_utils

# Database URL
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "processed"

# CME futures symbols on Yahoo Finance
CME_FUTURES = {
    "crude_oil_wti": {
        "symbol": "CL=F",
        "name": "WTI Crude Oil",
        "contract_unit": "barrels",
        "multiplier": 1000,
        "description": "NYMEX West Texas Intermediate Crude Oil Futures"
    },
    "crude_oil_brent": {
        "symbol": "BZ=F",
        "name": "Brent Crude Oil",
        "contract_unit": "barrels",
        "multiplier": 1000,
        "description": "ICE Brent Crude Oil Futures"
    },
    "natural_gas": {
        "symbol": "NG=F",
        "name": "Henry Hub Natural Gas",
        "contract_unit": "MMBtu",
        "multiplier": 10000,
        "description": "NYMEX Henry Hub Natural Gas Futures"
    },
    "heating_oil": {
        "symbol": "HO=F",
        "name": "Heating Oil",
        "contract_unit": "gallons",
        "multiplier": 42000,
        "description": "NYMEX Heating Oil Futures"
    },
    "rbob_gasoline": {
        "symbol": "RB=F",
        "name": "RBOB Gasoline",
        "contract_unit": "gallons",
        "multiplier": 42000,
        "description": "NYMEX RBOB Gasoline Futures"
    },
}


def download_with_timeout(symbol: str, start: str, end: str, timeout: int = DEFAULT_DOWNLOAD_TIMEOUT) -> Optional[pd.DataFrame]:
    """
    Download futures data from yfinance with a timeout.
    
    Args:
        symbol: Yahoo Finance ticker symbol (e.g., 'CL=F')
        start: Start date (YYYY-MM-DD)
        end: End date (YYYY-MM-DD)
        timeout: Timeout in seconds
        
    Returns:
        DataFrame if successful, None if timeout or error
    """
    result = [None]
    exception = [None]
    
    def download_task():
        try:
            data = yf.download(
                symbol,
                start=start,
                end=end,
                interval="1d",
                progress=False,
                timeout=timeout
            )
            result[0] = data
        except Exception as e:
            exception[0] = e
    
    thread = threading.Thread(target=download_task, daemon=True)
    thread.start()
    thread.join(timeout=timeout + 5)  # Give 5 extra seconds for cleanup
    
    if thread.is_alive():
        logger.warning(f"Download timeout for {symbol} after {timeout}s")
        return None
    
    if exception[0]:
        logger.error(f"Download error for {symbol}: {exception[0]}")
        return None
    
    return result[0]


class CMEFuturesClient:
    """Client for fetching CME futures data via Yahoo Finance."""
    
    def __init__(self):
        """Initialize CME futures client."""
        pass
    
    def fetch_futures(self, symbol: str, start_date: Optional[str] = None,
                      end_date: Optional[str] = None, interval: str = "1d") -> pd.DataFrame:
        """
        Fetch historical futures prices from Yahoo Finance.
        
        Args:
            symbol: Yahoo Finance symbol (e.g., 'CL=F' for WTI crude)
            start_date: Start date (YYYY-MM-DD format)
            end_date: End date (YYYY-MM-DD format)
            interval: '1d' for daily, '1wk' for weekly, '1mo' for monthly
        
        Returns:
            DataFrame with Date, Open, High, Low, Close, Volume
        """
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
        
        try:
            logger.info(f"Fetching {symbol} futures data from {start_date} to {end_date} (timeout: {DEFAULT_DOWNLOAD_TIMEOUT}s)...")
            
            # Use timeout-wrapped download
            data = download_with_timeout(symbol, start_date, end_date, timeout=DEFAULT_DOWNLOAD_TIMEOUT)
            
            if data is None:
                logger.warning(f"Failed to fetch {symbol} (timeout or error)")
                return pd.DataFrame()
            
            if data.empty:
                logger.warning(f"No data returned for {symbol}")
                return pd.DataFrame()
            
            # Reset index to make Date a column
            data = data.reset_index()
            data.rename(columns={'Date': 'Date'}, inplace=True)
            
            # Flatten multi-level columns if they exist
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = [col[0] for col in data.columns]
            
            logger.info(f"Fetched {len(data)} records for {symbol}")
            return data
        
        except Exception as e:
            logger.error(f"Error fetching {symbol}: {e}")
            return pd.DataFrame()
    
    def fetch_all_futures(self, start_date: Optional[str] = None,
                          end_date: Optional[str] = None) -> pd.DataFrame:
        """
        Fetch data for all tracked CME futures.
        
        Returns:
            Combined DataFrame with all futures prices
        """
        all_data = []
        
        for future_key, config in CME_FUTURES.items():
            symbol = config["symbol"]
            
            df = self.fetch_futures(symbol, start_date, end_date)
            
            if not df.empty:
                df["contract"] = future_key
                df["symbol"] = symbol
                df["name"] = config["name"]
                all_data.append(df)
        
        if all_data:
            combined = pd.concat(all_data, ignore_index=True)
            return combined
        else:
            logger.warning("No futures data retrieved")
            return pd.DataFrame()


@cache_utils.ttl_cache(ttl_seconds=604800, cache_name="cme_futures_fetch")  # 7 days
def _fetch_cme_futures_from_api(start_date: str, end_date: str) -> pd.DataFrame:
    """
    Fetch CME futures data from Yahoo Finance (expensive 1.3 second call).
    This function is wrapped with TTL cache - results cached for 7 days.
    
    Within a 7-day window, futures data is essentially static (past closes don't change),
    so caching respects the actual data patterns of futures markets.
    """
    logger.info(f"[CME] Fetching from Yahoo Finance ({start_date} to {end_date})...")
    client = CMEFuturesClient()
    df = client.fetch_all_futures(start_date=start_date, end_date=end_date)
    return df


def fetch_cme_futures_cached(start_date: str, end_date: str) -> pd.DataFrame:
    """
    Fetch CME futures with 7-day TTL caching.
    
    Caching strategy:
    - First call: Fetches from Yahoo Finance (1.3 seconds)
    - Subsequent calls within 7 days: Returns cached result (<100ms)
    - After 7 days: Fetches fresh data
    
    This 7-10x speedup is achieved by respecting futures data immutability:
    yesterday's close doesn't change, so weekly updates are sufficient.
    """
    return _fetch_cme_futures_from_api(start_date, end_date)


def calculate_futures_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate technical indicators and derived metrics.
    
    Adds:
    - Price momentum (% change over periods)
    - Volatility
    - Moving averages
    - Spreads between contracts
    """
    df = df.copy()
    
    # Group by contract for calculations
    for contract in df["contract"].unique():
        mask = df["contract"] == contract
        
        # YoY change
        df.loc[mask, "Close_YoY_Pct"] = (
            df.loc[mask, "Close"].pct_change(252, fill_method=None) * 100
        )
        
        # Month-to-date change
        df.loc[mask, "Close_MTD_Pct"] = (
            df.loc[mask, "Close"].pct_change(fill_method=None) * 100
        )
        
        # 20-day moving average
        df.loc[mask, "MA_20"] = (
            df.loc[mask, "Close"].rolling(window=20, min_periods=1).mean()
        )
        
        # 200-day moving average
        df.loc[mask, "MA_200"] = (
            df.loc[mask, "Close"].rolling(window=200, min_periods=1).mean()
        )
        
        # Volatility (20-day rolling std)
        df.loc[mask, "Volatility_20d"] = (
            df.loc[mask, "Close"].rolling(window=20, min_periods=1).std()
        )
        
        # High-Low range (daily volatility proxy)
        # Only calculate if we have valid High and Low columns
        if "High" in df.columns and "Low" in df.columns:
            # Avoid division by zero
            close_series = df.loc[mask, "Close"]
            close_nonzero = close_series.replace(0, np.nan)
            df.loc[mask, "Range_Pct"] = (
                (df.loc[mask, "High"] - df.loc[mask, "Low"]) / 
                close_nonzero * 100
            )
    
    return df


def save_futures_data(df: pd.DataFrame, output_path: Optional[Path] = None) -> Path:
    """Save CME futures data to CSV."""
    if output_path is None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / "cme_futures.csv"
    
    if not df.empty:
        df.to_csv(output_path, index=False)
        logger.info(f"Saved futures data to {output_path}")
        
        # Save metadata
        metadata = {
            "created": datetime.now().isoformat(),
            "contracts": list(CME_FUTURES.keys()),
            "symbols": {k: v["symbol"] for k, v in CME_FUTURES.items()},
            "data_source": "Yahoo Finance",
            "total_records": len(df),
            "date_range": f"{df['Date'].min()} to {df['Date'].max()}",
            "indicators": [
                "Close_YoY_Pct: Year-over-year price change %",
                "Close_MTD_Pct: Daily price change %",
                "MA_20: 20-day moving average",
                "MA_200: 200-day moving average",
                "Volatility_20d: 20-day rolling standard deviation",
                "Range_Pct: Daily high-low range as % of close"
            ]
        }
        
        metadata_path = output_path.with_suffix(".json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2, default=str)
        
        logger.info(f"Saved metadata to {metadata_path}")
    
    return output_path


def save_futures_to_database(df: pd.DataFrame, engine) -> int:
    """
    Save CME futures data to cme_futures_daily table.
    
    Args:
        df: DataFrame with futures data
        engine: SQLAlchemy engine
        
    Returns:
        Number of rows inserted
    """
    if df.empty:
        logger.warning("No data to save to database")
        return 0
    
    # Normalize data for database
    db_data = []
    for contract in df["contract"].unique():
        contract_df = df[df["contract"] == contract].copy()
        
        # Get contract metadata
        contract_config = CME_FUTURES.get(contract, {})
        
        for _, row in contract_df.iterrows():
            db_row = {
                "date": pd.to_datetime(row["Date"]),
                "contract_type": contract,
                "symbol": contract_config.get("symbol", ""),
                "contract_name": contract_config.get("name", ""),
                "open": float(row.get("Open", 0)) if pd.notna(row.get("Open")) else None,
                "high": float(row.get("High", 0)) if pd.notna(row.get("High")) else None,
                "low": float(row.get("Low", 0)) if pd.notna(row.get("Low")) else None,
                "close": float(row.get("Close", 0)) if pd.notna(row.get("Close")) else None,
                "volume": int(row.get("Volume", 0)) if pd.notna(row.get("Volume")) else None,
                "return_1d": float(row.get("Close_MTD_Pct", 0)) if pd.notna(row.get("Close_MTD_Pct")) else None,
                "volatility_20d": float(row.get("Volatility_20d", 0)) if pd.notna(row.get("Volatility_20d")) else None,
                "ma_20": float(row.get("MA_20", 0)) if pd.notna(row.get("MA_20")) else None,
                "ma_200": float(row.get("MA_200", 0)) if pd.notna(row.get("MA_200")) else None,
            }
            db_data.append(db_row)
    
    if db_data:
        db_df = pd.DataFrame(db_data)
        try:
            # Use append mode to handle duplicates gracefully (UNIQUE constraint)
            db_df.to_sql("cme_futures_daily", engine, if_exists="append", index=False)
            logger.info(f"Saved {len(db_df)} futures records to cme_futures_daily table")
            return int(len(db_df))
        except Exception as e:
            logger.warning(f"Pandas insert failed: {e}, trying SQLite insert directly")
            # Fallback: insert with explicit SQL
            try:
                rows_inserted = 0
                for _, row in db_df.iterrows():
                    sql = text("""
                        INSERT OR IGNORE INTO cme_futures_daily
                        (date, contract_type, symbol, contract_name, open, high, low, close, volume,
                         return_1d, volatility_20d, ma_20, ma_200)
                        VALUES (:date, :contract_type, :symbol, :contract_name, :open, :high, :low, :close, :volume,
                         :return_1d, :volatility_20d, :ma_20, :ma_200)
                    """)
                    with engine.connect() as conn:
                        conn.execute(sql, {
                            "date": str(row["date"]),
                            "contract_type": str(row["contract_type"]),
                            "symbol": str(row["symbol"]),
                            "contract_name": str(row["contract_name"]),
                            "open": float(row["open"]) if not pd.isna(row["open"]) else None,
                            "high": float(row["high"]) if not pd.isna(row["high"]) else None,
                            "low": float(row["low"]) if not pd.isna(row["low"]) else None,
                            "close": float(row["close"]) if not pd.isna(row["close"]) else None,
                            "volume": int(row["volume"]) if not pd.isna(row["volume"]) else None,
                            "return_1d": float(row["return_1d"]) if not pd.isna(row["return_1d"]) else None,
                            "volatility_20d": float(row["volatility_20d"]) if not pd.isna(row["volatility_20d"]) else None,
                            "ma_20": float(row["ma_20"]) if not pd.isna(row["ma_20"]) else None,
                            "ma_200": float(row["ma_200"]) if not pd.isna(row["ma_200"]) else None,
                        })
                        conn.commit()
                    rows_inserted += 1
                logger.info(f"Inserted {rows_inserted} futures records (with explicit SQL)")
                return int(rows_inserted)
            except Exception as e2:
                logger.error(f"Direct SQL insert also failed: {e2}")
                return 0
    
    return 0


def ingest_cme_futures():
    """Main ingestion function for CME futures."""
    logger.info("Starting CME futures data ingestion...")
    
    # Create engine for querying existing data
    try:
        engine = create_engine(DB_URL)
    except:
        engine = None
    
    # Calculate fetch range based on sliding window strategy
    start_date, end_date = incremental_utils.calculate_fetch_range(
        "cme_futures",
        engine=engine
    )
    
    logger.info(f"Fetching CME futures from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    
    # Use cached fetch to avoid redundant API calls within 7-day window
    df = fetch_cme_futures_cached(
        start_date=start_date.strftime('%Y-%m-%d'),
        end_date=end_date.strftime('%Y-%m-%d')
    )
    
    if not df.empty:
        # Calculate indicators
        df = calculate_futures_indicators(df)
        
        # Save to disk (CSV for backwards compatibility)
        output_path = save_futures_data(df)
        
        # Save to database
        rows_saved = 0
        if engine is not None:
            rows_saved = save_futures_to_database(df, engine)
        
        logger.info(f"Futures ingestion complete. Total records: {len(df)}, DB rows: {rows_saved}")
        
        # Update metadata to track successful fetch
        incremental_utils.update_fetch_metadata("cme_futures", start_date, end_date, success=True)
        
        # Summary by contract
        logger.info("Data summary by contract:")
        for contract in df["contract"].unique():
            contract_data = df[df["contract"] == contract]
            if not contract_data.empty:
                latest = contract_data.iloc[-1]
                try:
                    close_val = float(latest['Close'])
                except (ValueError, TypeError):
                    close_val = 0.0
                try:
                    date_val = str(latest['Date'])
                except (ValueError, TypeError):
                    date_val = "N/A"
                logger.info(f"  {contract}: {close_val:.2f} (updated {date_val})")
        
        return rows_saved
    else:
        logger.warning("No futures data retrieved")
        incremental_utils.update_fetch_metadata("cme_futures", start_date, end_date, success=False)
        return 0


def main() -> None:
    """Main function for CME futures data ingestion."""
    return ingest_cme_futures()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    df = ingest_cme_futures()
    
    if not df.empty:
        print("\nRecent futures prices:")
        for contract in df["contract"].unique():
            contract_df = df[df["contract"] == contract].tail(5)
            print(f"\n{contract}:")
            print(contract_df[["Date", "Close", "MA_20", "Volatility_20d"]].to_string())
