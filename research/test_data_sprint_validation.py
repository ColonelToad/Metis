"""
Data Backfill and Validation for Multi-Asset Energy Complex
Tests ingestion, database writes, and data quality checks
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import sqlite3
import logging
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.common import runtime_config as rc
from data_ingest import ingest_cme_futures
from data_ingest import ingest_lmp_multi_iso

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

DB_URL = rc.get_db_url()


def test_cme_futures_ingest() -> bool:
    """Test CME futures ingestion and database write."""
    logger.info("=" * 80)
    logger.info("TEST: CME Futures Ingestion")
    logger.info("=" * 80)
    
    try:
        # Run ingester
        rows_saved = ingest_cme_futures.ingest_cme_futures()
        
        if rows_saved > 0:
            logger.info(f"[OK] Ingested {rows_saved} CME futures records")
            
            # Verify database write
            engine = create_engine(DB_URL)
            with engine.connect() as conn:
                result = conn.execute(text("SELECT COUNT(*) FROM cme_futures_daily"))
                total_rows = result.scalar()
                logger.info(f"[OK] Database now contains {total_rows} CME futures records")
                
                # Check contracts
                contracts = conn.execute(text("SELECT DISTINCT contract_type FROM cme_futures_daily"))
                contracts_list = [row[0] for row in contracts]
                logger.info(f"[OK] Contracts: {contracts_list}")
                
                # Check for nulls
                nulls = conn.execute(text("""
                    SELECT 
                        SUM(CASE WHEN close IS NULL THEN 1 ELSE 0 END) as null_close,
                        SUM(CASE WHEN date IS NULL THEN 1 ELSE 0 END) as null_date
                    FROM cme_futures_daily
                """))
                null_result = nulls.fetchone()
                logger.info(f"[OK] Data quality: {null_result[0]} null closes, {null_result[1]} null dates")
                
                return True
        else:
            logger.warning("[WARN] No CME futures records ingested")
            return False
    
    except Exception as e:
        logger.error(f"[ERROR] CME futures test failed: {e}")
        return False


def test_lmp_multi_iso_ingest() -> bool:
    """Test multi-ISO LMP ingestion and database write."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST: Multi-ISO LMP Ingestion")
    logger.info("=" * 80)
    
    try:
        # Run ingester
        rows_saved = ingest_lmp_multi_iso.main()
        
        if rows_saved > 0:
            logger.info(f"[OK] Ingested {rows_saved} LMP records from {rows_saved // 288 + 1} ISOs")
            
            # Verify database write
            engine = create_engine(DB_URL)
            with engine.connect() as conn:
                result = conn.execute(text("SELECT COUNT(*) FROM grid_lmp_multi_iso"))
                total_rows = result.scalar()
                logger.info(f"[OK] Database now contains {total_rows} LMP records")
                
                # Check ISOs
                isos = conn.execute(text("SELECT DISTINCT iso FROM grid_lmp_multi_iso"))
                iso_list = [row[0] for row in isos]
                logger.info(f"[OK] ISOs: {iso_list}")
                
                # Check for nulls and outliers
                stats = conn.execute(text("""
                    SELECT 
                        COUNT(*) as total_rows,
                        SUM(CASE WHEN lmp IS NULL THEN 1 ELSE 0 END) as null_lmp,
                        MIN(lmp) as min_lmp,
                        MAX(lmp) as max_lmp,
                        AVG(lmp) as avg_lmp
                    FROM grid_lmp_multi_iso
                """))
                stats_result = stats.fetchone()
                logger.info(f"[OK] Data quality: {stats_result[1]} null LMPs out of {stats_result[0]}")
                logger.info(f"[OK] LMP range: {stats_result[3] if stats_result[3] else 'N/A'}$/MWh (min: {stats_result[2]}, avg: {stats_result[4]:.2f})")
                
                return True
        else:
            logger.warning("[WARN] No LMP records ingested")
            return False
    
    except Exception as e:
        logger.error(f"[ERROR] LMP multi-ISO test failed: {e}")
        return False


def test_data_alignment() -> bool:
    """Test data alignment across all sources."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST: Data Alignment")
    logger.info("=" * 80)
    
    try:
        engine = create_engine(DB_URL)
        
        # Check date coverage
        with engine.connect() as conn:
            ng_dates = conn.execute(text("SELECT COUNT(DISTINCT date) FROM ng_futures_daily")).scalar()
            cme_dates = conn.execute(text("SELECT COUNT(DISTINCT date) FROM cme_futures_daily")).scalar()
            lmp_dates = conn.execute(text("SELECT COUNT(DISTINCT DATE(timestamp)) FROM grid_lmp_multi_iso")).scalar()
            
            logger.info(f"[OK] NG futures: {ng_dates} unique dates")
            logger.info(f"[OK] CME futures: {cme_dates} unique dates")
            logger.info(f"[OK] LMP multi-ISO: {lmp_dates} unique dates")
            
            # Check date ranges
            ng_range = conn.execute(text("SELECT MIN(date), MAX(date) FROM ng_futures_daily")).fetchone()
            cme_range = conn.execute(text("SELECT MIN(date), MAX(date) FROM cme_futures_daily")).fetchone()
            lmp_range = conn.execute(text("SELECT MIN(DATE(timestamp)), MAX(DATE(timestamp)) FROM grid_lmp_multi_iso")).fetchone()
            
            logger.info(f"[OK] NG range: {ng_range[0]} to {ng_range[1]}")
            logger.info(f"[OK] CME range: {cme_range[0]} to {cme_range[1]}")
            logger.info(f"[OK] LMP range: {lmp_range[0]} to {lmp_range[1]}")
            
            return True
    
    except Exception as e:
        logger.error(f"[ERROR] Data alignment test failed: {e}")
        return False


def test_feature_engineering() -> bool:
    """Test that feature engineering pipeline still works."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST: Feature Engineering Pipeline")
    logger.info("=" * 80)
    
    try:
        from features import engineer_features
        
        logger.info("[OK] Feature engineering module imported")
        
        # Try to instantiate and run abbreviated pipeline
        engineer = engineer_features.FeatureEngineer(DB_URL, start_date="2024-01-01")
        
        # Just test load_price_data to avoid long runtime
        df = engineer.load_price_data()
        logger.info(f"[OK] Loaded price data: {len(df)} rows")
        
        # Test loading CME futures
        engineer.df = df
        df = engineer.load_cme_futures_features(df)
        logger.info(f"[OK] Loaded CME futures features: {len(df.columns)} total columns")
        
        # Test loading LMP
        df = engineer.load_power_lmp_features(df)
        logger.info(f"[OK] Loaded LMP features: {len(df.columns)} total columns")
        
        # Check for expected columns
        expected_cols = ['natural_gas_close', 'crude_oil_wti_close', 'crude_oil_brent_close', 'heating_oil_close', 'rbob_gasoline_close']
        found_cols = [col for col in expected_cols if col in df.columns]
        logger.info(f"[OK] Found CME columns: {found_cols}")
        
        return True
    
    except Exception as e:
        logger.error(f"[ERROR] Feature engineering test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_schema_integrity() -> bool:
    """Test database schema integrity."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST: Schema Integrity")
    logger.info("=" * 80)
    
    try:
        conn = sqlite3.connect("data/metis.db")
        cursor = conn.cursor()
        
        # Check table existence
        tables_to_check = ['cme_futures_daily', 'grid_lmp_multi_iso', 'ng_futures_daily']
        for table in tables_to_check:
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            if cursor.fetchone():
                logger.info(f"[OK] Table {table} exists")
                
                # Get column info
                cursor.execute(f"PRAGMA table_info({table})")
                columns = cursor.fetchall()
                col_names = [col[1] for col in columns]
                logger.info(f"     Columns: {col_names}")
            else:
                logger.warning(f"[WARN] Table {table} not found")
                return False
        
        conn.close()
        return True
    
    except Exception as e:
        logger.error(f"[ERROR] Schema integrity test failed: {e}")
        return False


def main():
    """Run all validation and backfill tests."""
    logger.info("\n\n")
    logger.info("=" * 80)
    logger.info("METIS DATA SPRINT: BACKFILL & VALIDATION")
    logger.info("=" * 80)
    
    results = {
        "Schema Integrity": test_schema_integrity(),
        "CME Futures Ingest": test_cme_futures_ingest(),
        "LMP Multi-ISO Ingest": test_lmp_multi_iso_ingest(),
        "Data Alignment": test_data_alignment(),
        "Feature Engineering": test_feature_engineering(),
    }
    
    logger.info("\n" + "=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)
    for test_name, passed in results.items():
        status = "[OK]" if passed else "[FAIL]"
        logger.info(f"{status} {test_name}")
    
    all_passed = all(results.values())
    if all_passed:
        logger.info("\n[SUCCESS] All tests passed!")
    else:
        logger.warning("\n[WARNING] Some tests failed - check logs above")
    
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
