"""
NOAA NCEI Storm Events Ingestion
Fetches detailed storm event data from NCEI's static bulk CSV file directory
(SWDI bulk download: https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/),
NOT the Access Data Service query API -- that endpoint doesn't serve this
dataset and returns 400 for any dataset name. No API key required.

Each year has a 'details' file named like:
    StormEvents_details-ftp_v1.0_d{YEAR}_c{CREATION_DATE}.csv.gz
The creation-date suffix changes whenever NCEI revises that year's data
(confirmed: several recent years were revised as late as mid-2026), so the
current filename per year must be discovered from the live directory listing,
not constructed from a guessed date.
"""
import os
import re
import gzip
from io import BytesIO
from pathlib import Path
from datetime import datetime
import pandas as pd
import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
METIS_MODE = os.getenv("METIS_MODE", "DEV")


def require_real_mode(source: str) -> bool:
    if METIS_MODE not in ("REAL", "PROD"):
        print(f"[DEV MODE] Skipping {source}")
        return False
    return True


SWDI_BASE_URL = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"
CACHE_DIR = Path("data/cache/storm_events")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Matches e.g. StormEvents_details-ftp_v1.0_d2024_c20260421.csv.gz -> ('2024', '20260421')
_FILENAME_RE = re.compile(r'StormEvents_details-ftp_v1\.0_d(\d{4})_c(\d{8})\.csv\.gz')


def get_current_filenames() -> dict:
    """
    Fetch the SWDI directory listing once and return {year: (filename, creation_date)}
    for the current 'details' file per year. A year can appear multiple times in
    listing history if revised -- keep the entry with the latest creation date.
    """
    resp = requests.get(SWDI_BASE_URL, timeout=60)
    resp.raise_for_status()
    matches = _FILENAME_RE.findall(resp.text)

    latest = {}
    for year_str, cdate in matches:
        year = int(year_str)
        if year not in latest or cdate > latest[year]:
            latest[year] = cdate

    return {
        year: (f"StormEvents_details-ftp_v1.0_d{year}_c{cdate}.csv.gz", cdate)
        for year, cdate in latest.items()
    }


def download_year(year: int, filename_map: dict = None) -> pd.DataFrame:
    """
    Download one year of storm event details. Cache key embeds the creation
    date from the live listing, so a revised file (new creation date) is
    automatically treated as new data rather than silently served from a
    stale cache -- this matters since recent years get revised months later.
    """
    if not require_real_mode("NOAA Storm Events"):
        return pd.DataFrame()

    if filename_map is None:
        filename_map = get_current_filenames()

    if year not in filename_map:
        print(f"No details file found for {year} in NCEI directory listing")
        return pd.DataFrame()

    filename, cdate = filename_map[year]
    cache_file = CACHE_DIR / f"storm_events_{year}_{cdate}.parquet"

    if cache_file.exists():
        print(f"Loading storm events from cache: {year} (creation date {cdate})")
        return pd.read_parquet(cache_file)

    url = SWDI_BASE_URL + filename
    print(f"Downloading {year} storm events: {filename}")

    try:
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        with gzip.GzipFile(fileobj=BytesIO(resp.content)) as gz:
            df = pd.read_csv(gz, low_memory=False)

        df.columns = df.columns.str.strip().str.upper()
        if 'BEGIN_DATE_TIME' in df.columns:
            df['BEGIN_DATE_TIME'] = pd.to_datetime(df['BEGIN_DATE_TIME'], errors='coerce')
        if 'END_DATE_TIME' in df.columns:
            df['END_DATE_TIME'] = pd.to_datetime(df['END_DATE_TIME'], errors='coerce')

        df.to_parquet(cache_file)
        print(f"Cached {len(df)} storm events for {year}")
        return df
    except Exception as e:
        print(f"Error downloading {year} storm events ({filename}): {e}")
        return pd.DataFrame()


def download_range(start_year: int, end_year: int) -> pd.DataFrame:
    """Download multiple years of storm events."""
    filename_map = get_current_filenames()
    if filename_map:
        print(f"NCEI directory has {len(filename_map)} years available "
              f"({min(filename_map)}-{max(filename_map)})")

    all_data = []
    for year in range(start_year, end_year + 1):
        df = download_year(year, filename_map=filename_map)
        if not df.empty:
            all_data.append(df)

    return pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame()


def parse_damage_value(val):
    """
    Parse NCEI damage strings like '10.00K', '2.5M', '1.2B' into raw dollar
    amounts. Bare pd.to_numeric(errors='coerce') silently turns every one of
    these into NaN, since the K/M/B suffix makes them non-numeric strings --
    this was a second, quieter bug sitting underneath the original 400 errors.
    """
    if pd.isna(val):
        return None
    s = str(val).strip().upper()
    if s in ('', 'NAN'):
        return None
    if s == '0' or s == '0.00':
        return 0.0
    multipliers = {'K': 1e3, 'M': 1e6, 'B': 1e9}
    suffix = s[-1]
    if suffix in multipliers:
        try:
            return float(s[:-1]) * multipliers[suffix]
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def normalize_and_save(df: pd.DataFrame) -> int:
    """Normalize NCEI storm data and save to SQLite. Returns row count saved."""
    if df.empty:
        print("No storm event data to save")
        return 0

    df.columns = df.columns.str.strip().str.upper()

    df_normalized = pd.DataFrame({
        'event_id': df['EPISODE_ID'].astype(str) + '_' + df['EVENT_ID'].astype(str),
        'state': df.get('STATE', ''),
        'county': df.get('COUNTY_FIPS', ''),
        'event_type': df.get('EVENT_TYPE', ''),
        'begin_date': df.get('BEGIN_DATE_TIME'),
        'end_date': df.get('END_DATE_TIME'),
        'property_damage': df.get('DAMAGE_PROPERTY', pd.Series(dtype=object)).apply(parse_damage_value),
        'crop_damage': df.get('DAMAGE_CROPS', pd.Series(dtype=object)).apply(parse_damage_value),
        'injuries_direct': pd.to_numeric(df.get('INJURIES_DIRECT', 0), errors='coerce'),
        'deaths_direct': pd.to_numeric(df.get('DEATHS_DIRECT', 0), errors='coerce'),
        'magnitude': pd.to_numeric(df.get('MAGNITUDE', None), errors='coerce'),
        'magnitude_type': df.get('MAGNITUDE_TYPE', ''),
        'timestamp': datetime.now()
    })

    df_normalized = df_normalized.drop_duplicates(subset=['event_id'])

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
        return len(df_normalized)
    except Exception as e:
        print(f"Error saving storm events to database: {e}")
        return 0


def main():
    print(f"[{METIS_MODE}] NOAA Storm Events")
    start_year = int(os.getenv("STORM_EVENTS_START_YEAR", "2015"))
    end_year = datetime.now().year
    print(f"Fetching NOAA storm events ({start_year}-{end_year})...")

    df = download_range(start_year, end_year)

    if not df.empty:
        print(f"Fetched {len(df)} storm events total")
        return normalize_and_save(df)
    else:
        print("No storm event data fetched")
        return 0


if __name__ == "__main__":
    main()
