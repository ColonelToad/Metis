"""
Backfill historical data for multi-asset energy complex.
- CME Futures: 10 years (2016-2026)
- LMP Multi-ISO: 5 years (2021-2026)

Run from workspace root: python research/backfill_multi_asset_data.py
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
import logging

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.data_ingest import ingest_cme_futures
from research.data_ingest import ingest_lmp_multi_iso
from research.data_ingest import incremental_utils

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def backfill_cme_futures():
    """
    Backfill CME futures for 10 years (2016-2026).
    """
    logger.info("=" * 80)
    logger.info("BACKFILL: CME Futures (10 years)")
    logger.info("=" * 80)
    
    start_date = (datetime.now() - timedelta(days=3650)).strftime("%Y-%m-%d")  # ~10 years
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    logger.info(f"Fetching CME futures from {start_date} to {end_date}")
    
    try:
        # Fetch and save
        rows_saved = ingest_cme_futures.ingest_cme_futures()
        
        logger.info(f"✓ CME futures backfill: {rows_saved} records saved")
        
        # Verify database
        from sqlalchemy import create_engine, text
        import os
        DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
        engine = create_engine(DB_URL)
        
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM cme_futures_daily"))
            total = result.scalar()
            
            result = conn.execute(text("SELECT MIN(date), MAX(date) FROM cme_futures_daily"))
            date_range = result.fetchone()
            
            logger.info(f"  Database: {total} total records, range: {date_range[0]} to {date_range[1]}")
        
        return True
    
    except Exception as e:
        logger.error(f"✗ CME futures backfill failed: {e}", exc_info=True)
        return False


def backfill_lmp_multi_iso():
    """
    Backfill LMP for 5 years (2021-2026).
    Note: gridstatus may have limited historical data; CAISO typically has 1-2 years.
    """
    logger.info("\n" + "=" * 80)
    logger.info("BACKFILL: LMP Multi-ISO (5 years, depth-limited by API availability)")
    logger.info("=" * 80)
    
    start_date = (datetime.now() - timedelta(days=1825)).strftime("%Y-%m-%d")  # ~5 years
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    logger.info(f"Attempting LMP backfill from {start_date} to {end_date}")
    logger.info("Note: Historical depth varies by ISO (CAISO: ~2 years, NYISO: ~3 years)")
    
    try:
        # Run main ingester (uses last_date logic)
        rows_saved = ingest_lmp_multi_iso.main()
        
        if rows_saved > 0:
            logger.info(f"✓ LMP multi-ISO backfill: {rows_saved} records saved")
        else:
            logger.warning(f"⚠ LMP multi-ISO: {rows_saved} records (may be empty in DEV mode)")
        
        # Verify database
        from sqlalchemy import create_engine, text
        import os
        DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
        engine = create_engine(DB_URL)
        
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM grid_lmp_multi_iso"))
            total = result.scalar()
            
            result = conn.execute(text("""
                SELECT iso, COUNT(*) as count 
                FROM grid_lmp_multi_iso 
                GROUP BY iso 
                ORDER BY iso
            """))
            iso_counts = result.fetchall()
            
            logger.info(f"  Database: {total} total records")
            for iso, count in iso_counts:
                logger.info(f"    - {iso}: {count} records")
        
        return True
    
    except Exception as e:
        logger.error(f"✗ LMP multi-ISO backfill failed: {e}", exc_info=True)
        return False


def main():
    """Run full backfill sequence."""
    logger.info("\n" + "=" * 80)
    logger.info("METIS MULTI-ASSET BACKFILL")
    logger.info("=" * 80)
    
    results = {
        "CME Futures (10Y)": backfill_cme_futures(),
        "LMP Multi-ISO (5Y)": backfill_lmp_multi_iso(),
    }
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("BACKFILL SUMMARY")
    logger.info("=" * 80)
    for name, success in results.items():
        status = "✓ SUCCESS" if success else "✗ FAILED"
        logger.info(f"{status}: {name}")
    
    all_ok = all(results.values())
    if all_ok:
        logger.info("\n✓ All backfills completed successfully!")
        logger.info("Ready to run feature engineering and correlation analysis.")
    else:
        logger.warning("\n⚠ Some backfills had issues - check logs above")
    
    return all_ok


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
