"""
Incremental ingestion utilities - backfill and sliding window strategies.

Provides smart date range calculation for different ingestion strategies:
- Backfill: Progressively fetch historical data backward
- Sliding Window: Maintain rolling N-year window of recent data
- Incremental: Only fetch new data since last run
"""

import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple, Optional, Dict, Literal
import logging

logger = logging.getLogger(__name__)

# Configuration for each ingester's fetch strategy
INGESTER_CONFIG = {
    "fred_building_permits": {
        "mode": "backfill",           # progressive backfill
        "target_years": 10,           # goal: 10 years of data
        "chunk_years": 1,             # fetch 1 year per run
        "overlap_days": 30,           # overlap to catch corrections
        "db_table": "census_permits"
    },
    
    "cme_futures": {
        "mode": "sliding_window",     # just maintain rolling 2 years
        "window_years": 2,
        "overlap_days": 7,
        "db_table": "cme_futures"
    },
    
    "lmp": {
        "mode": "incremental",        # only new data
        "lookback_days": 7,           # but always check last 7 days for corrections
        "db_table": "caiso_lmp"
    },
    
    "ingest_fred": {
        "mode": "sliding_window",
        "window_years": 2,
        "overlap_days": 30,
        "db_table": "fred_macro"
    },
    
    "ingest_eia": {
        "mode": "incremental",
        "lookback_days": 30,
        "db_table": "eia_storage"
    }
}

# Metadata storage location
METADATA_DIR = Path(__file__).parent.parent / "data" / "ingestion_metadata"
METADATA_DIR.mkdir(parents=True, exist_ok=True)


def get_metadata_path(ingester_name: str) -> Path:
    """Get path to metadata file for ingester."""
    return METADATA_DIR / f"{ingester_name}_metadata.json"


def load_metadata(ingester_name: str) -> Dict:
    """Load ingestion metadata (last_fetch_date, first_record_date, etc.)."""
    metadata_path = get_metadata_path(ingester_name)
    
    if metadata_path.exists():
        try:
            with open(metadata_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load metadata for {ingester_name}: {e}")
            return {}
    
    return {}


def save_metadata(ingester_name: str, metadata: Dict) -> None:
    """Save ingestion metadata."""
    metadata_path = get_metadata_path(ingester_name)
    metadata['last_updated'] = datetime.now().isoformat()
    
    try:
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to save metadata for {ingester_name}: {e}")


def update_fetch_metadata(ingester_name: str, start_date: datetime, end_date: datetime, success: bool = True) -> None:
    """Update metadata after a successful fetch."""
    metadata = load_metadata(ingester_name)
    
    if success:
        metadata['last_fetch_start'] = start_date.isoformat()
        metadata['last_fetch_end'] = end_date.isoformat()
        metadata['last_fetch_success'] = datetime.now().isoformat()
        metadata['fetch_count'] = metadata.get('fetch_count', 0) + 1
    else:
        metadata['last_fetch_failed'] = datetime.now().isoformat()
    
    save_metadata(ingester_name, metadata)


def get_last_ingestion_date(engine, table_name: str) -> Optional[datetime]:
    """Get the latest date in the database for a table."""
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            result = conn.execute(text(f"""
                SELECT MAX(date) as last_date FROM {table_name}
            """))
            row = result.fetchone()
            if row and row[0]:
                date_val = row[0]
                if isinstance(date_val, str):
                    return datetime.fromisoformat(date_val)
                return date_val
    except Exception as e:
        logger.warning(f"Could not get last ingestion date for {table_name}: {e}")
    
    return None


def get_first_ingestion_date(engine, table_name: str) -> Optional[datetime]:
    """Get the earliest date in the database for a table."""
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            result = conn.execute(text(f"""
                SELECT MIN(date) as first_date FROM {table_name}
            """))
            row = result.fetchone()
            if row and row[0]:
                date_val = row[0]
                if isinstance(date_val, str):
                    return datetime.fromisoformat(date_val)
                return date_val
    except Exception as e:
        logger.warning(f"Could not get first ingestion date for {table_name}: {e}")
    
    return None


def calculate_fetch_range(
    ingester_name: str,
    engine=None,
    force_mode: Optional[Literal["backfill", "incremental", "sliding_window"]] = None
) -> Tuple[datetime, datetime]:
    """
    Calculate the date range to fetch for an ingester.
    
    Args:
        ingester_name: Name of ingester (e.g., 'fred_building_permits')
        engine: SQLAlchemy engine for querying existing data
        force_mode: Override the configured mode (for testing)
    
    Returns:
        (start_date, end_date) tuple for fetching
    """
    
    if ingester_name not in INGESTER_CONFIG:
        logger.warning(f"No config for {ingester_name}, using incremental with 30-day lookback")
        return (datetime.now() - timedelta(days=30), datetime.now())
    
    config = INGESTER_CONFIG[ingester_name]
    mode = force_mode or config.get('mode', 'incremental')
    table_name = config.get('db_table', ingester_name)
    
    end_date = datetime.now()
    
    if mode == "incremental":
        """Only fetch new data since last run, with lookback for corrections."""
        lookback = config.get('lookback_days', 7)
        
        if engine:
            last_date = get_last_ingestion_date(engine, table_name)
            if last_date:
                # Check for corrections: overlap with last few days
                start_date = last_date - timedelta(days=lookback)
                logger.info(f"[{ingester_name}] Incremental mode: fetching from {start_date} to {end_date}")
                return (start_date, end_date)
        
        # First run: get lookback period
        start_date = end_date - timedelta(days=lookback)
        logger.info(f"[{ingester_name}] First run (incremental): fetching last {lookback} days")
        return (start_date, end_date)
    
    elif mode == "sliding_window":
        """Maintain a rolling window of recent data."""
        window_years = config.get('window_years', 2)
        overlap_days = config.get('overlap_days', 7)
        window_days = int(window_years * 365.25)
        
        start_date = end_date - timedelta(days=window_days)
        
        if engine:
            last_date = get_last_ingestion_date(engine, table_name)
            if last_date:
                # Optimize: overlap to catch corrections, but don't re-fetch everything
                start_date = last_date - timedelta(days=overlap_days)
                logger.info(f"[{ingester_name}] Sliding window: fetching from {start_date} to {end_date}")
                return (start_date, end_date)
        
        logger.info(f"[{ingester_name}] First run (sliding_window): fetching {window_years} years")
        return (start_date, end_date)
    
    elif mode == "backfill":
        """Progressive backfill: extend window backward until target_years is reached."""
        target_years = config.get('target_years', 10)
        chunk_years = config.get('chunk_years', 1)
        overlap_days = config.get('overlap_days', 30)
        
        target_start = end_date - timedelta(days=int(target_years * 365.25))
        
        if engine:
            first_record = get_first_ingestion_date(engine, table_name)
            
            if first_record is None:
                # No data yet: fetch first chunk
                chunk_days = int(chunk_years * 365.25)
                start_date = end_date - timedelta(days=chunk_days)
                logger.info(f"[{ingester_name}] Backfill (first chunk): fetching {chunk_years} years")
                return (start_date, end_date)
            
            elif first_record > target_start:
                # Continue backfilling: extend window backward
                chunk_days = int(chunk_years * 365.25)
                extend_to = first_record - timedelta(days=1)
                start_date = max(extend_to - timedelta(days=chunk_days), target_start)
                
                backfill_progress = (end_date - first_record).days / (end_date - target_start).days * 100
                logger.info(f"[{ingester_name}] Backfilling ({backfill_progress:.1f}% complete): fetching from {start_date} to {extend_to}")
                return (start_date, extend_to)
            
            else:
                # Backfill complete: switch to incremental with overlap
                last_date = get_last_ingestion_date(engine, table_name)
                if last_date:
                    start_date = last_date - timedelta(days=overlap_days)
                    logger.info(f"[{ingester_name}] Backfill complete, now incremental: fetching from {start_date} to {end_date}")
                    return (start_date, end_date)
        
        # First run: fetch first chunk
        chunk_days = int(chunk_years * 365.25)
        start_date = end_date - timedelta(days=chunk_days)
        logger.info(f"[{ingester_name}] Backfill (first chunk): fetching {chunk_years} years")
        return (start_date, end_date)
    
    else:
        raise ValueError(f"Unknown ingestion mode: {mode}")


# Convenience function for quick access
def get_fetch_dates(ingester_name: str, engine=None) -> Tuple[str, str]:
    """Get fetch dates as ISO strings (YYYY-MM-DD format)."""
    start, end = calculate_fetch_range(ingester_name, engine)
    return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')
