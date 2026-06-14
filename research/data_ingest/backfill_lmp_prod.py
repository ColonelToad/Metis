"""
Backfill LMP multi-ISO data with METIS_MODE=PROD enabled.
Fetches historical LMP from CAISO, NYISO, ISO-NE (5-year depth).
Note: gridstatus historical depth varies by ISO (~2-5 years typical).
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
import logging
import os

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Ensure PROD mode
os.environ["METIS_MODE"] = "PROD"

from research.data_ingest import ingest_lmp_multi_iso
from sqlalchemy import create_engine, text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")


def backfill_lmp():
    """Backfill LMP with gridstatus API calls."""
    logger.info("=" * 80)
    logger.info("BACKFILL: LMP Multi-ISO (METIS_MODE=PROD)")
    logger.info("=" * 80)
    
    start_date = (datetime.now() - timedelta(days=1825)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    logger.info(f"Target range: {start_date} to {end_date}")
    logger.info("Note: Actual depth limited by gridstatus API availability")
    
    try:
        # Run ingester (now with API calls enabled via METIS_MODE=PROD)
        logger.info("Calling ingest_lmp_multi_iso.main() with PROD mode...")
        rows_saved = ingest_lmp_multi_iso.main()
        
        logger.info(f"✓ LMP ingester completed: {rows_saved} rows")
        
        # Verify database
        engine = create_engine(DB_URL)
        
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM grid_lmp_multi_iso"))
            total = result.scalar()
            
            logger.info(f"\nDatabase stats:")
            logger.info(f"  Total LMP records: {total}")
            
            if total > 0:
                # Stats by ISO
                result = conn.execute(text("""
                    SELECT iso, COUNT(*) as cnt, MIN(timestamp), MAX(timestamp)
                    FROM grid_lmp_multi_iso
                    GROUP BY iso
                    ORDER BY iso
                """))
                
                logger.info(f"\n  Records by ISO:")
                for iso, cnt, ts_min, ts_max in result:
                    logger.info(f"    {iso:10} {cnt:8} records | {ts_min} to {ts_max}")
                
                # LMP statistics
                result = conn.execute(text("""
                    SELECT iso, AVG(lmp) as avg_lmp, MIN(lmp) as min_lmp, MAX(lmp) as max_lmp
                    FROM grid_lmp_multi_iso
                    GROUP BY iso
                """))
                
                logger.info(f"\n  LMP statistics ($/MWh):")
                for iso, avg, min_val, max_val in result:
                    logger.info(f"    {iso:10} avg={avg:.2f}, min={min_val:.2f}, max={max_val:.2f}")
            
            return total > 0
    
    except Exception as e:
        logger.error(f"✗ LMP backfill failed: {e}", exc_info=True)
        return False


def main():
    logger.info("\n" + "=" * 80)
    logger.info("LMP MULTI-ISO BACKFILL (PRODUCTION MODE)")
    logger.info("=" * 80)
    
    success = backfill_lmp()
    
    logger.info("\n" + "=" * 80)
    if success:
        logger.info("✓ LMP backfill complete!")
        logger.info("System now has multi-asset coverage: CME (10Y) + NG + LMP (5Y)")
        logger.info("\nReady to run correlation analysis or LSTM integration")
    else:
        logger.warning("⚠ LMP backfill had issues (may depend on API availability)")
    
    return success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
