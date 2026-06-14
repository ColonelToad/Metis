"""
Direct backfill bypassing incremental cache.
Fetches full date ranges from source APIs directly.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
import logging
import pandas as pd
from sqlalchemy import create_engine, text
import os

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.data_ingest.ingest_cme_futures import (
    CMEFuturesClient, calculate_futures_indicators, CME_FUTURES
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")


def backfill_cme_full_range():
    """Fetch CME futures for 10 years, bypassing cache."""
    logger.info("=" * 80)
    logger.info("BACKFILL: CME Futures (10-year full range, bypass cache)")
    logger.info("=" * 80)
    
    start_date = (datetime.now() - timedelta(days=3650)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    logger.info(f"Fetching {start_date} to {end_date}")
    
    try:
        # Use client directly (bypasses cache)
        client = CMEFuturesClient()
        df = client.fetch_all_futures(start_date, end_date)
        
        if df.empty:
            logger.warning("No data returned from CME API")
            return 0
        
        logger.info(f"Fetched {len(df)} records from API")
        
        # Calculate indicators
        df = calculate_futures_indicators(df)
        
        # Save to database
        engine = create_engine(DB_URL)
        db_data = []
        
        for contract in df["contract"].unique():
            contract_df = df[df["contract"] == contract].copy()
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
            # Clear existing and insert
            with engine.connect() as conn:
                conn.execute(text("DELETE FROM cme_futures_daily"))
                conn.commit()
                logger.info("Cleared existing records")
            
            db_df = pd.DataFrame(db_data)
            db_df.to_sql("cme_futures_daily", engine, if_exists="append", index=False)
            logger.info(f"✓ Inserted {len(db_df)} records")
            
            # Verify
            with engine.connect() as conn:
                result = conn.execute(text("SELECT COUNT(*) FROM cme_futures_daily"))
                total = result.scalar()
                
                result = conn.execute(text("SELECT MIN(date), MAX(date) FROM cme_futures_daily"))
                date_min, date_max = result.fetchone()
                
                logger.info(f"  Database: {total} records, range: {date_min} to {date_max}")
                
                # Summary by contract
                result = conn.execute(text("""
                    SELECT contract_type, COUNT(*) as cnt, MIN(date), MAX(date)
                    FROM cme_futures_daily
                    GROUP BY contract_type
                """))
                for contract, cnt, date_min, date_max in result:
                    logger.info(f"    {contract}: {cnt} records ({date_min} to {date_max})")
            
            return len(db_df)
        else:
            logger.warning("No data to insert")
            return 0
    
    except Exception as e:
        logger.error(f"✗ Backfill failed: {e}", exc_info=True)
        return 0


def main():
    logger.info("\n" + "=" * 80)
    logger.info("DIRECT BACKFILL (bypass cache)")
    logger.info("=" * 80)
    
    rows = backfill_cme_full_range()
    
    logger.info("\n" + "=" * 80)
    if rows > 0:
        logger.info(f"✓ SUCCESS: {rows} records backfilled")
        logger.info("Ready for feature engineering and correlation analysis")
    else:
        logger.info("⚠ No new records added")
    
    return rows > 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
