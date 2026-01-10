"""
NOAA NCEI Storm Events Ingestion
Fetches detailed storm event data from NCEI database
No API key required - bulk CSV downloads
"""
import os
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import time
from io import StringIO
import requests

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
METIS_MODE = os.getenv("METIS_MODE", "DEV")


def require_real_mode(source: str) -> bool:
    if METIS_MODE != "REAL":
        print(f"[DEV MODE] Skipping {source}")
        return False
    return True

NCEI_ADS_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
CACHE_DIR = Path("data/cache/storm_events")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def download_year(year: int, use_cache: bool = True) -> pd.DataFrame:
    """
    Download full year of storm events via NCEI Access Data Service (CSV).
    """
    if not require_real_mode("NOAA Storm Events"):
        return pd.DataFrame()

    cache_file = CACHE_DIR / f"storm_events_{year}.parquet"

    if use_cache and cache_file.exists():
        print(f"Loading storm events from cache: {year}")
        return pd.read_parquet(cache_file)

    dataset_candidates = [
        "stormevents",  # primary ADS dataset name
        "stormevents-details",
        "stormevents_details",
    ]

    last_err = None
    for ds in dataset_candidates:
        params = {
            "dataset": ds,
            "startDate": f"{year}-01-01",
            "endDate": f"{year}-12-31",
            "format": "csv",
        }

        print(f"Downloading {year} storm events via NCEI ADS (dataset={ds})...")
        try:
            resp = requests.get(NCEI_ADS_URL, params=params, timeout=120)
            resp.raise_for_status()
            df = pd.read_csv(StringIO(resp.text))

            # Clean data
            if 'BEGIN_DATE_TIME' in df.columns:
                df['BEGIN_DATE_TIME'] = pd.to_datetime(df['BEGIN_DATE_TIME'], errors='coerce')
            if 'END_DATE_TIME' in df.columns:
                df['END_DATE_TIME'] = pd.to_datetime(df['END_DATE_TIME'], errors='coerce')

            df.to_parquet(cache_file)
            print(f"Cached {len(df)} storm events for {year}")
            return df
        except Exception as e:
            last_err = e
            print(f"Error downloading {year} storm events with dataset {ds}: {e}")
            continue

    print(f"All dataset attempts failed for {year}. Last error: {last_err}")
    return pd.DataFrame()


def download_range(start_year: int, end_year: int) -> pd.DataFrame:
    """Download multiple years of storm events"""
    all_data = []
    
    for year in range(start_year, end_year + 1):
        df = download_year(year)
        if not df.empty:
            all_data.append(df)
            time.sleep(1)  # Rate limiting
    
    return pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame()


def normalize_and_save(df: pd.DataFrame) -> None:
    """Normalize NCEI storm data and save to SQLite"""
    if df.empty:
        print("No storm event data to save")
        return
    
    # Normalize column names
    df.columns = df.columns.str.strip().str.upper()
    
    # Create normalized dataframe with key columns
    df_normalized = pd.DataFrame({
        'event_id': df['EPISODE_ID'].astype(str) + '_' + df['EVENT_ID'].astype(str),
        'state': df.get('STATE', ''),
        'county': df.get('COUNTY_FIPS', ''),
        'event_type': df.get('EVENT_TYPE', ''),
        'begin_date': df.get('BEGIN_DATE_TIME'),
        'end_date': df.get('END_DATE_TIME'),
        'property_damage': pd.to_numeric(df.get('DAMAGE_PROPERTY', 0), errors='coerce'),
        'crop_damage': pd.to_numeric(df.get('DAMAGE_CROPS', 0), errors='coerce'),
        'injuries_direct': pd.to_numeric(df.get('INJURIES_DIRECT', 0), errors='coerce'),
        'deaths_direct': pd.to_numeric(df.get('DEATHS_DIRECT', 0), errors='coerce'),
        'magnitude': pd.to_numeric(df.get('MAGNITUDE', None), errors='coerce'),
        'magnitude_type': df.get('MAGNITUDE_TYPE', ''),
        'timestamp': datetime.now()
    })
    
    # Drop duplicates based on event_id
    df_normalized = df_normalized.drop_duplicates(subset=['event_id'])
    
    # Normalize datetimes to naive Python values for SQLite binding
    for col in ['begin_date', 'end_date', 'timestamp']:
        if col in df_normalized.columns:
            df_normalized[col] = pd.to_datetime(df_normalized[col], errors='coerce').dt.tz_localize(None)

    def _to_py(val):
        if pd.isna(val):
            return None
        if isinstance(val, pd.Timestamp):
            return val.to_pydatetime()
        return val
    
    try:
        engine = create_engine(DB_URL)
        backend = engine.url.get_backend_name()

        with engine.begin() as conn:
            if backend == "sqlite":
                cols = [
                    'event_id', 'state', 'county', 'event_type', 'begin_date', 'end_date',
                    'property_damage', 'crop_damage', 'injuries_direct', 'deaths_direct',
                    'magnitude', 'magnitude_type', 'timestamp'
                ]
                records = []
                for row in df_normalized.itertuples(index=False):
                    records.append({
                        'event_id': row.event_id,
                        'state': row.state,
                        'county': row.county,
                        'event_type': row.event_type,
                        'begin_date': _to_py(row.begin_date),
                        'end_date': _to_py(row.end_date),
                        'property_damage': None if pd.isna(row.property_damage) else float(row.property_damage),
                        'crop_damage': None if pd.isna(row.crop_damage) else float(row.crop_damage),
                        'injuries_direct': None if pd.isna(row.injuries_direct) else int(row.injuries_direct),
                        'deaths_direct': None if pd.isna(row.deaths_direct) else int(row.deaths_direct),
                        'magnitude': None if pd.isna(row.magnitude) else float(row.magnitude),
                        'magnitude_type': row.magnitude_type,
                        'timestamp': _to_py(row.timestamp)
                    })
                placeholders = ", ".join([f":{c}" for c in cols])
                update_clause = ", ".join([f"{c}=excluded.{c}" for c in cols if c != 'event_id'])
                stmt = text(
                    f"""
                    INSERT INTO storm_events ({', '.join(cols)})
                    VALUES ({placeholders})
                    ON CONFLICT(event_id) DO UPDATE SET {update_clause}
                    """
                )
                conn.execute(stmt, records)
            else:
                df_normalized.to_sql(
                    'storm_events',
                    conn,
                    if_exists='append',
                    index=False,
                    method='multi'
                )

        print(f"Saved {len(df_normalized)} storm event records to database")
    except Exception as e:
        print(f"Error saving storm events to database: {e}")


if __name__ == "__main__":
    print(f"[{METIS_MODE}] NOAA Storm Events")

    # Backfill 5 years of data
    print("Fetching NOAA storm events (2021-2025)...")

    df = download_range(2021, 2025)

    if not df.empty:
        print(f"Fetched {len(df)} storm events total")
        normalize_and_save(df)
    else:
        print("No storm event data fetched")
