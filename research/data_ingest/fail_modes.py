"""
Fail Mode Handling for Data Ingestion Pipeline

Provides:
- Retry decorator with exponential backoff
- Fallback data source (previous successful run)
- Data validation framework (schema, nulls, duplicates)
- Anomaly detection (z-score, percent change, missing data)
- Graceful degradation patterns
"""

import functools
import time
import sqlite3
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from typing import Callable, Any, Dict, List, Tuple, Optional
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database path
DB_PATH = Path(__file__).parent.parent.parent / 'data' / 'metis.db'


# ============================================================================
# RETRY LOGIC
# ============================================================================

def with_retry(
    max_attempts: int = 3,
    backoff_factor: float = 2.0,
    timeout: int = 300,
    exception_types: Tuple = (Exception,)
) -> Callable:
    """
    Decorator: Retry function with exponential backoff.
    
    Usage:
        @with_retry(max_attempts=3, backoff_factor=2.0, timeout=300)
        def ingest_data():
            # API call
            pass
    
    Args:
        max_attempts: Number of retry attempts (default 3)
        backoff_factor: Multiplier for exponential backoff (default 2.0)
        timeout: Timeout per attempt in seconds (default 300 = 5 min)
        exception_types: Tuple of exception types to catch (default all)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            delay = 1  # Start with 1 second
            
            for attempt in range(1, max_attempts + 1):
                try:
                    logger.info(f"Attempt {attempt}/{max_attempts} for {func.__name__}")
                    return func(*args, **kwargs)
                    
                except exception_types as e:
                    if attempt == max_attempts:
                        logger.error(f"All {max_attempts} attempts failed: {e}")
                        raise
                    
                    logger.warning(
                        f"Attempt {attempt} failed: {e}. "
                        f"Retrying in {delay}s (max {max_attempts} attempts)"
                    )
                    time.sleep(delay)
                    delay = int(delay * backoff_factor)  # Exponential backoff
            
        return wrapper
    return decorator


# ============================================================================
# FALLBACK HANDLING
# ============================================================================

def fallback_on_error() -> bool:
    """
    Fallback: Use previous day's data if current ingestion fails.
    
    Logic:
    1. Check if backup from previous run exists
    2. If yes, copy backup to live tables
    3. Update metadata to mark as fallback
    4. Log the event
    
    Returns:
        True if fallback successful, False otherwise
    """
    try:
        logger.info("Attempting fallback to previous data...")
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()
        
        # Check if backup tables exist
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name LIKE '%_backup'
        """)
        backup_tables = [row[0] for row in cursor.fetchall()]
        
        if not backup_tables:
            logger.warning("No backup tables found")
            return False
        
        # Restore from backups
        for backup_table in backup_tables:
            live_table = backup_table.replace('_backup', '')
            cursor.execute(f"DROP TABLE IF EXISTS {live_table}")
            cursor.execute(f"ALTER TABLE {backup_table} RENAME TO {live_table}")
            logger.info(f"Restored {live_table} from backup")
        
        # Record fallback event
        cursor.execute("""
            INSERT INTO ingestion_log (timestamp, source, status, fallback)
            VALUES (?, ?, ?, ?)
        """, (datetime.now(), 'FALLBACK', 'SUCCESS', 1))
        
        db.commit()
        db.close()
        
        logger.info("✓ Fallback successful")
        return True
        
    except Exception as e:
        logger.error(f"✗ Fallback failed: {e}")
        return False


def create_backup(table_name: str) -> bool:
    """Create backup of table before new ingestion."""
    try:
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()
        
        # Create backup by copying
        backup_table = f"{table_name}_backup"
        cursor.execute(f"DROP TABLE IF EXISTS {backup_table}")
        cursor.execute(f"CREATE TABLE {backup_table} AS SELECT * FROM {table_name}")
        
        db.commit()
        db.close()
        logger.info(f"✓ Backup created: {backup_table}")
        return True
        
    except Exception as e:
        logger.warning(f"Could not create backup for {table_name}: {e}")
        return False


# ============================================================================
# DATA VALIDATION FRAMEWORK
# ============================================================================

class DataValidator:
    """Validates ingested data against schema, nulls, duplicates, types."""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db = sqlite3.connect(db_path)
        self.errors = []
        self.warnings = []
    
    def validate_schema(self, table_name: str, expected_columns: List[str]) -> bool:
        """Check that table has all expected columns."""
        try:
            df = pd.read_sql_query(f"SELECT * FROM {table_name} LIMIT 1", self.db)
            missing_cols = set(expected_columns) - set(df.columns)
            
            if missing_cols:
                self.errors.append(
                    f"{table_name}: Missing columns {missing_cols}"
                )
                return False
            
            logger.info(f"✓ {table_name}: Schema valid")
            return True
            
        except Exception as e:
            self.errors.append(f"{table_name}: {e}")
            return False
    
    def validate_nulls(
        self,
        table_name: str,
        critical_columns: Optional[List[str]] = None,
        warning_threshold: float = 0.05
    ) -> bool:
        """
        Check null values.
        
        Args:
            table_name: Table to validate
            critical_columns: Columns that must not be null
            warning_threshold: Warn if null% > threshold (default 5%)
        """
        try:
            df = pd.read_sql_query(f"SELECT * FROM {table_name}", self.db)
            null_counts = df.isnull().sum()
            
            # Critical: no nulls allowed
            if critical_columns:
                for col in critical_columns:
                    if col in null_counts and null_counts[col] > 0:
                        self.errors.append(
                            f"{table_name}: Critical column '{col}' has {null_counts[col]} nulls"
                        )
                        return False
            
            # Warnings: nulls above threshold
            for col, null_count in null_counts.items():
                null_pct = null_count / len(df)
                if null_pct > warning_threshold:
                    self.warnings.append(
                        f"{table_name}: Column '{col}' is {null_pct*100:.1f}% null"
                    )
            
            logger.info(f"✓ {table_name}: Null check passed")
            return True
            
        except Exception as e:
            self.errors.append(f"{table_name}: Null check error: {e}")
            return False
    
    def validate_duplicates(self, table_name: str, key_columns: List[str]) -> bool:
        """Check for duplicate key combinations."""
        try:
            df = pd.read_sql_query(f"SELECT * FROM {table_name}", self.db)
            
            # Check exact duplicates
            exact_dups = df.duplicated().sum()
            if exact_dups > 0:
                self.warnings.append(
                    f"{table_name}: {exact_dups} exact duplicate rows"
                )
            
            # Check key duplicates
            if key_columns:
                key_dups = df.duplicated(subset=key_columns, keep='last').sum()
                if key_dups > 0:
                    self.errors.append(
                        f"{table_name}: {key_dups} duplicate keys on {key_columns}"
                    )
                    return False
            
            logger.info(f"✓ {table_name}: Duplicate check passed")
            return True
            
        except Exception as e:
            self.errors.append(f"{table_name}: Duplicate check error: {e}")
            return False
    
    def validate_chronological_order(
        self,
        table_name: str,
        date_column: str,
        allow_future_dates: bool = False
    ) -> bool:
        """Check that dates are in order and not in the future."""
        try:
            df = pd.read_sql_query(
                f"SELECT {date_column} FROM {table_name} ORDER BY {date_column}",
                self.db
            )
            
            df[date_column] = pd.to_datetime(df[date_column])
            
            # Check for future dates
            if not allow_future_dates:
                future = (df[date_column] > datetime.now()).sum()
                if future > 0:
                    self.warnings.append(
                        f"{table_name}: {future} future-dated records"
                    )
            
            # Check ordering
            is_sorted = df[date_column].is_monotonic_increasing
            if not is_sorted:
                self.warnings.append(
                    f"{table_name}: Data not chronologically sorted"
                )
            
            logger.info(f"✓ {table_name}: Chronological check passed")
            return True
            
        except Exception as e:
            self.errors.append(f"{table_name}: Date check error: {e}")
            return False
    
    def validate_numeric_ranges(
        self,
        table_name: str,
        column: str,
        min_val: Optional[float] = None,
        max_val: Optional[float] = None
    ) -> bool:
        """Check numeric columns are within expected range."""
        try:
            df = pd.read_sql_query(f"SELECT {column} FROM {table_name}", self.db)
            
            out_of_range = 0
            if min_val is not None:
                out_of_range += (df[column] < min_val).sum()
            if max_val is not None:
                out_of_range += (df[column] > max_val).sum()
            
            if out_of_range > 0:
                self.warnings.append(
                    f"{table_name}.{column}: {out_of_range} values out of range "
                    f"[{min_val}, {max_val}]"
                )
            
            return True
            
        except Exception as e:
            self.errors.append(f"{table_name}: Range check error: {e}")
            return False
    
    def is_valid(self) -> bool:
        """Return True if no critical errors (warnings ok)."""
        if self.errors:
            logger.error(f"Validation errors:\n" + "\n".join(self.errors))
            return False
        if self.warnings:
            logger.warning(f"Validation warnings:\n" + "\n".join(self.warnings))
        return True
    
    def close(self):
        self.db.close()


def validate_ingestion() -> bool:
    """Run full validation suite on all ingested tables."""
    validator = DataValidator()
    
    try:
        # Define validation rules per table
        rules = {
            'equities_stooq': {
                'schema': ['ticker', 'date', 'open', 'high', 'low', 'close', 'volume'],
                'critical_nulls': ['ticker', 'date', 'close'],
                'keys': ['ticker', 'date'],
                'date_col': 'date',
            },
            'macro_fred': {
                'schema': ['series_id', 'date', 'value'],
                'critical_nulls': ['series_id', 'date', 'value'],
                'keys': ['series_id', 'date'],
                'date_col': 'date',
            },
            'weather_nws': {
                'schema': ['grid_point', 'timestamp', 'temp', 'precip_prob', 'wind_speed'],
                'critical_nulls': ['grid_point', 'timestamp'],
                'keys': ['grid_point', 'timestamp'],
                'date_col': 'timestamp',
            },
        }
        
        all_valid = True
        for table_name, rules_dict in rules.items():
            try:
                if not validator.validate_schema(table_name, rules_dict.get('schema', [])):
                    all_valid = False
                    continue
                
                if not validator.validate_nulls(
                    table_name, 
                    rules_dict.get('critical_nulls')
                ):
                    all_valid = False
                    continue
                
                if not validator.validate_duplicates(
                    table_name,
                    rules_dict.get('keys', [])
                ):
                    all_valid = False
                    continue
                
                if 'date_col' in rules_dict:
                    if not validator.validate_chronological_order(
                        table_name,
                        rules_dict['date_col']
                    ):
                        all_valid = False
                        
            except sqlite3.OperationalError:
                # Table doesn't exist yet (new ingestion), skip
                logger.info(f"⊘ {table_name}: Table not yet created")
        
        return all_valid
        
    finally:
        validator.close()


# ============================================================================
# ANOMALY DETECTION
# ============================================================================

def check_anomalies(
    lookback_days: int = 30,
    zscore_threshold: float = 3.0,
    pct_change_threshold: float = 0.20
) -> Dict[str, List[str]]:
    """
    Detect data anomalies using statistical methods.
    
    Args:
        lookback_days: Window for historical comparison
        zscore_threshold: Flag if |z-score| > threshold (default 3.0 = 3-sigma)
        pct_change_threshold: Flag if daily change > threshold (default 20%)
    
    Returns:
        Dict mapping table names to list of anomaly descriptions
    """
    anomalies = {}
    db = sqlite3.connect(DB_PATH)
    
    try:
        # Price anomalies (equities, futures)
        df = pd.read_sql_query("""
            SELECT ticker, date, close 
            FROM equities_stooq 
            WHERE date > datetime('now', '-30 days')
            ORDER BY ticker, date
        """, db)
        
        if len(df) > 0:
            df['pct_change'] = df.groupby('ticker')['close'].pct_change().abs()
            df['zscore'] = df.groupby('ticker')['close'].apply(
                lambda x: np.abs((x - x.mean()) / x.std())
            )
            
            # Percent change anomalies
            pct_anomalies = df[df['pct_change'] > pct_change_threshold]
            if len(pct_anomalies) > 0:
                anomalies['equities_stooq_pct_change'] = [
                    f"{row['ticker']} on {row['date']}: {row['pct_change']*100:.1f}% move"
                    for _, row in pct_anomalies.iterrows()
                ]
            
            # Z-score anomalies
            zscore_anomalies = df[df['zscore'] > zscore_threshold]
            if len(zscore_anomalies) > 0:
                anomalies['equities_stooq_zscore'] = [
                    f"{row['ticker']} on {row['date']}: zscore={row['zscore']:.1f}"
                    for _, row in zscore_anomalies.iterrows()
                ]
        
        # Volume anomalies
        df_vol = pd.read_sql_query("""
            SELECT ticker, date, volume
            FROM equities_stooq 
            WHERE date > datetime('now', '-30 days')
            ORDER BY ticker, date
        """, db)
        
        if len(df_vol) > 0:
            df_vol['vol_zscore'] = df_vol.groupby('ticker')['volume'].apply(
                lambda x: np.abs((x - x.mean()) / x.std())
            )
            
            vol_anomalies = df_vol[df_vol['vol_zscore'] > zscore_threshold]
            if len(vol_anomalies) > 0:
                anomalies['equities_stooq_volume'] = [
                    f"{row['ticker']} on {row['date']}: volume zscore={row['vol_zscore']:.1f}"
                    for _, row in vol_anomalies.iterrows()
                ]
        
        # Missing data checks
        cursor = db.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        missing_tables = []
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            if count == 0:
                missing_tables.append(table)
        
        if missing_tables:
            anomalies['missing_data'] = [f"Empty table: {t}" for t in missing_tables]
        
        if anomalies:
            logger.warning(f"Anomalies detected: {anomalies}")
        else:
            logger.info("✓ No anomalies detected")
        
        return anomalies
        
    except Exception as e:
        logger.error(f"Anomaly detection error: {e}")
        return {'error': [str(e)]}
    
    finally:
        db.close()


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

if __name__ == '__main__':
    # Example: Retry decorator
    @with_retry(max_attempts=3, backoff_factor=2.0)
    def sample_ingest():
        """Sample ingestion function."""
        print("Attempting ingest...")
        # This would fail randomly for demo
        return True
    
    # Example: Validation
    print("\n=== Data Validation ===")
    if validate_ingestion():
        print("✓ All validations passed")
    else:
        print("✗ Validation failed")
    
    # Example: Anomaly detection
    print("\n=== Anomaly Detection ===")
    anomalies = check_anomalies()
    if anomalies:
        for category, items in anomalies.items():
            print(f"{category}:")
            for item in items[:5]:  # Show first 5
                print(f"  - {item}")
