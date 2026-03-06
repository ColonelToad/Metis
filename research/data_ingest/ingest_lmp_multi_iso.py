"""
Multi-ISO Grid LMP Data Ingestion using gridstatus
Fetches real-time and day-ahead LMP for CAISO, NYISO, ISO-NE, PJM, ERCOT
Consolidates into unified grid_lmp_multi_iso table with ISO labels
"""
import os
import sys
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta
import gridstatus
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import logging

# Add project root for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.common import runtime_config as rc
from research.common import cache_utils
from data_ingest import incremental_utils

load_dotenv()
DB_URL = rc.get_db_url()

logger = logging.getLogger(__name__)

# Cache directory
CACHE_DIR = Path("data/cache/lmp")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ISO configurations: (iso_class, iso_name, fetch_params)
ISO_CONFIGS = [
    (gridstatus.CAISO(), "CAISO", {"market": "REAL_TIME_5_MIN"}),
    (gridstatus.NYISO(), "NYISO", {"market": "REAL_TIME_5_MIN"}),
    (gridstatus.ISONE(), "ISO-NE", {"market": "REAL_TIME_5_MIN"}),
]

# PJM requires an API key - only include if available
pjm_key = os.getenv("PJM_API_KEY")
if pjm_key:
    ISO_CONFIGS.append((gridstatus.PJM(api_key=pjm_key), "PJM", {}))
else:
    logger.warning("PJM_API_KEY not set - skipping PJM data fetch")

# ERCOT: Will be added separately since it has different API signature


def get_cache_key(iso_name, start_date, end_date):
    """Generate cache filename based on query params"""
    key_str = f"{iso_name.lower()}_{start_date.date()}_{end_date.date()}"
    return f"{key_str}.parquet"


@cache_utils.ttl_cache(ttl_seconds=3600, cache_name="lmp_multi_iso")
def _fetch_iso_lmp_from_api(iso_name: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
    """
    Fetch ISO LMP data from gridstatus API (expensive call).
    This function is wrapped with TTL cache - results cached for 1 hour.
    """
    logger.info(f"[LMP] Fetching {iso_name} from gridstatus ({start_date.date()})...")
    
    # Find matching ISO config
    iso_obj = None
    fetch_params = {}
    for iso, iso_n, params in ISO_CONFIGS:
        if iso_n == iso_name:
            iso_obj = iso
            fetch_params = params
            break
    
    if iso_obj is None:
        logger.warning(f"ISO {iso_name} not configured in ISO_CONFIGS")
        return pd.DataFrame()
    
    try:
        df = iso_obj.get_lmp(date=start_date, **fetch_params)
        if not df.empty:
            df["iso"] = iso_name
            # Standardize timestamp column
            if "Time" in df.columns:
                df["timestamp"] = pd.to_datetime(df["Time"])
            elif "Timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["Timestamp"])
            else:
                df["timestamp"] = pd.to_datetime(df.index) if df.index.name else pd.Timestamp.now()
            
            return df
        else:
            logger.warning(f"[LMP] Empty result for {iso_name}")
            return pd.DataFrame()
    except Exception as e:
        logger.error(f"[LMP] Error fetching {iso_name}: {type(e).__name__}: {str(e)[:150]}")
        return pd.DataFrame()


def fetch_iso_lmp(iso_name: str, start_date: datetime, end_date: datetime, use_cache=True) -> pd.DataFrame:
    """
    Fetch ISO LMP data with TTL caching.
    
    Caching strategy:
    - First call: Fetches from ISO API (slow)
    - Subsequent calls within 1 hour: Returns cached result (<100ms)
    - After 1 hour: Fetches fresh data
    """
    if not rc.require_real_mode(f"{iso_name} LMP API"):
        return pd.DataFrame()
    
    return _fetch_iso_lmp_from_api(iso_name, start_date, end_date)


def normalize_lmp_data(df: pd.DataFrame, iso_name: str) -> pd.DataFrame:
    """
    Normalize LMP data from various ISOs to standard schema.
    
    Standard columns:
    - timestamp: Datetime of LMP observation
    - iso: ISO name
    - node_id: Location/node identifier
    - location_name: Human-readable location name
    - market: Market type (REAL_TIME_5_MIN, etc.)
    - lmp: Locational Marginal Price ($/MWh)
    - energy_component: LMP component breakdown
    - congestion_component: LMP component breakdown
    - loss_component: LMP component breakdown
    """
    if df.empty:
        return pd.DataFrame()
    
    normalized = pd.DataFrame()
    
    # Map source columns based on ISO
    if iso_name == "CAISO":
        normalized = df[[
            "timestamp", "Location", "Market", "LMP"
        ]].copy() if all(col in df.columns for col in ["timestamp", "Location", "Market", "LMP"]) else pd.DataFrame()
        normalized.columns = ["timestamp", "node_id", "market", "lmp"]
        normalized["location_name"] = normalized["node_id"]
    
    elif iso_name == "NYISO":
        normalized = df[[
            "timestamp", "Location", "Market", "LMP"
        ]].copy() if all(col in df.columns for col in ["timestamp", "Location", "Market", "LMP"]) else pd.DataFrame()
        normalized.columns = ["timestamp", "node_id", "market", "lmp"]
        normalized["location_name"] = normalized["node_id"]
    
    elif iso_name == "ISO-NE":
        normalized = df[[
            "timestamp", "Location", "Market", "LMP"
        ]].copy() if all(col in df.columns for col in ["timestamp", "Location", "Market", "LMP"]) else pd.DataFrame()
        normalized.columns = ["timestamp", "node_id", "market", "lmp"]
        normalized["location_name"] = normalized["node_id"]
    
    elif iso_name == "PJM":
        # PJM might have different column names - handle gracefully
        if "LMP" in df.columns:
            normalized = df[[
                "timestamp", "LMP"
            ]].copy() if "timestamp" in df.columns else pd.DataFrame()
            if not normalized.empty:
                normalized.columns = ["timestamp", "lmp"]
                normalized["node_id"] = df.get("Location", df.get("Node ID", "PJM_HUB"))
                normalized["location_name"] = df.get("Location Name", normalized["node_id"])
                normalized["market"] = "REAL_TIME"
    
    if not normalized.empty:
        normalized["iso"] = iso_name
        # Ensure timestamp is datetime
        normalized["timestamp"] = pd.to_datetime(normalized["timestamp"])
        # Clean LMP values
        normalized["lmp"] = pd.to_numeric(normalized["lmp"], errors="coerce")
        # Optional component columns
        normalized["energy_component"] = None
        normalized["congestion_component"] = None
        normalized["loss_component"] = None
        normalized["node_type"] = None
    
    return normalized


def save_lmp_to_database(df: pd.DataFrame, engine) -> int:
    """
    Save normalized LMP data to grid_lmp_multi_iso table.
    
    Returns:
        Number of rows inserted
    """
    if df.empty:
        logger.warning("No LMP data to save")
        return 0
    
    try:
        # Use INSERT OR IGNORE to handle duplicates
        df.to_sql("grid_lmp_multi_iso", engine, if_exists="append", index=False)
        logger.info(f"Saved {len(df)} LMP records to database")
        return len(df)
    except Exception as e:
        logger.error(f"Error saving LMP to database: {e}")
        # Try with conflict handling
        try:
            with engine.connect() as conn:
                insert_sql = """
                    INSERT OR IGNORE INTO grid_lmp_multi_iso
                    (timestamp, iso, node_id, node_type, location_name, market, lmp,
                     energy_component, congestion_component, loss_component)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                rows_inserted = 0
                for _, row in df.iterrows():
                    conn.execute(insert_sql, (
                        row["timestamp"], row["iso"], row["node_id"], row.get("node_type"),
                        row.get("location_name"), row.get("market"), row.get("lmp"),
                        row.get("energy_component"), row.get("congestion_component"),
                        row.get("loss_component")
                    ))
                    rows_inserted += 1
                conn.commit()
                logger.info(f"Inserted {rows_inserted} LMP records (with conflict handling)")
                return rows_inserted
        except Exception as e2:
            logger.error(f"Conflict handling also failed: {e2}")
            return 0


def main():
    """Main ingestion function for multi-ISO LMP."""
    rc.log_mode("LMP-MULTI-ISO")
    
    # Create engine for database operations
    try:
        engine = create_engine(DB_URL)
    except:
        logger.error("Failed to create database engine")
        return 0
    
    # Calculate fetch range based on incremental strategy with 7-day lookback
    start_date, end_date = incremental_utils.calculate_fetch_range(
        "lmp_multi_iso",
        engine=engine
    )
    
    logger.info(f"Fetching multi-ISO LMP data ({start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')})")
    
    total_rows = 0
    
    # Fetch from each configured ISO
    for iso_name, _, _ in [(name, obj, params) for obj, name, params in ISO_CONFIGS]:
        try:
            logger.info(f"Fetching {iso_name}...")
            lmp_df = fetch_iso_lmp(iso_name, start_date, end_date)
            
            if not lmp_df.empty:
                logger.info(f"  Fetched {len(lmp_df)} {iso_name} records")
                
                # Normalize to standard schema
                normalized = normalize_lmp_data(lmp_df, iso_name)
                
                if not normalized.empty:
                    # Save to database
                    rows_saved = save_lmp_to_database(normalized, engine)
                    total_rows += rows_saved
                    logger.info(f"  Saved {rows_saved} {iso_name} records")
                else:
                    logger.warning(f"  Failed to normalize {iso_name} data")
            else:
                logger.warning(f"  No {iso_name} data retrieved")
        
        except Exception as e:
            logger.error(f"Error processing {iso_name}: {type(e).__name__}: {str(e)[:150]}")
            continue
    
    # Update metadata
    if total_rows > 0:
        incremental_utils.update_fetch_metadata("lmp_multi_iso", start_date, end_date, success=True)
        logger.info(f"Multi-ISO LMP ingestion complete. Total records: {total_rows}")
    else:
        logger.warning("No LMP data ingested successfully")
        incremental_utils.update_fetch_metadata("lmp_multi_iso", start_date, end_date, success=False)
    
    return total_rows


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    total = main()
    print(f"\nMulti-ISO LMP ingestion completed: {total} records")
