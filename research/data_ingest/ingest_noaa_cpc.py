"""
NOAA CPC Daily Population-Weighted Degree Days Ingestion

Ingests NOAA Climate Prediction Center daily heating/cooling degree days,
population-weighted (2010 Census/ACS weights), which is the demand-side
series EIA itself uses for storage analysis:

  - State + CONUS level (StatesCONUS files)
  - Census-division level (Population files)
  - Gas-heating-customer-weighted HDD (UtilityGas) - the sharpest direct
    proxy for residential NG heating demand
  - Electricity-customer-weighted HDD/CDD (power-demand proxy)
  - 1981-2010 daily climatology normals -> anomaly computation baseline

Source layout (verified Aug 2026):
  https://ftp.cpc.ncep.noaa.gov/htdocs/degree_days/weighted/daily_data/
    {YEAR}/<Weight>.<Heating|Cooling>.txt     # pipe-delimited, one file per year
    latest/<...>.txt                          # current year-to-date mirror
    climatology/1981-2010/<...>.txt           # MMDD-keyed daily normals

File format: 3 metadata lines, then 'Region|YYYYMMDD|...' header, then
rows 'RegionID|v|v|...' (values < -900 treated as missing).

Known data-quality incidents (per CPC): real-time values Aug-Oct 2009 and
Jan-Apr 2008 were corrupted and later re-run; archives hold corrected data.

USAGE:
  python ingest_noaa_cpc.py                # incremental (new years + current)
  python ingest_noaa_cpc.py --full         # force backfill from 1981
  python ingest_noaa_cpc.py --dry-run
"""

import argparse
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
DB_PATH = DB_URL.replace("sqlite:///", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BASE = "https://ftp.cpc.ncep.noaa.gov/htdocs/degree_days/weighted/daily_data"

# (file stem, weight_basis, degree_type, region_type)
# NOTE: CPC publishes fuel-weighted files (UtilityGas/Electricity/etc.)
# HEATING-only; cooling exists only population-weighted.
FILES = [
    ("StatesCONUS.Heating", "population", "HDD", "states_conus"),
    ("StatesCONUS.Cooling", "population", "CDD", "states_conus"),
    ("Population.Heating", "population", "HDD", "census_division"),
    ("Population.Cooling", "population", "CDD", "census_division"),
    ("UtilityGas.Heating", "utility_gas", "HDD", "census_division"),
    ("Electricity.Heating", "electricity", "HDD", "census_division"),
]

# CPC census-division IDs (standard Census nomenclature)
CENSUS_DIVISIONS = {
    "1": "New England",
    "2": "Middle Atlantic",
    "3": "East North Central",
    "4": "West North Central",
    "5": "South Atlantic",
    "6": "East South Central",
    "7": "West South Central",
    "8": "Mountain",
    "9": "Pacific",
}
MISSING_THRESHOLD = -900


def _fetch(url: str):
    r = requests.get(url, timeout=60)
    if r.status_code != 200:
        return None
    return r.text


def parse_dd_file(text: str):
    """Yield (region_id, date_iso_or_mmdd, value). Returns also whether dates
    are full ISO dates or MMDD normals."""
    lines = text.splitlines()
    header_idx = next(i for i, l in enumerate(lines) if l.startswith("Region|"))
    cols = lines[header_idx].split("|")[1:]
    is_normals = len(cols[0]) == 4  # MMDD
    out = []
    for line in lines[header_idx + 1 :]:
        parts = line.split("|")
        if len(parts) < 2:
            continue
        rid = parts[0].strip()
        if not rid or rid.lower() == "region":
            continue
        for col, raw in zip(cols, parts[1:]):
            try:
                v = float(raw)
            except ValueError:
                continue
            if v <= MISSING_THRESHOLD:
                v = None
            if is_normals:
                date_key = col
            else:
                try:
                    date_key = datetime.strptime(col.strip(), "%Y%m%d").strftime("%Y-%m-%d")
                except ValueError:
                    continue
            out.append((rid, date_key, v))
    return out


def ensure_tables(conn: sqlite3.Connection):
    conn.execute("""CREATE TABLE IF NOT EXISTS noaa_degree_days (
            region_type TEXT NOT NULL, region TEXT NOT NULL,
            weight_basis TEXT NOT NULL, degree_type TEXT NOT NULL,
            date TEXT NOT NULL, value REAL, fetched_at TEXT,
            PRIMARY KEY (region_type, region, weight_basis, degree_type, date))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS noaa_dd_normals (
            region_type TEXT NOT NULL, region TEXT NOT NULL,
            weight_basis TEXT NOT NULL, degree_type TEXT NOT NULL,
            mmdd TEXT NOT NULL, normal REAL, fetched_at TEXT,
            PRIMARY KEY (region_type, region, weight_basis, degree_type, mmdd))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS ingest_meta (
            key TEXT PRIMARY KEY, value TEXT)""")
    conn.commit()


def get_meta(conn, key):
    row = conn.execute("SELECT value FROM ingest_meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO ingest_meta (key, value) VALUES (?,?)", (key, str(value)))
    conn.commit()


def write_rows(conn, rows, normals=False, dry_run=False):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    table = "noaa_dd_normals" if normals else "noaa_degree_days"
    date_col = "mmdd" if normals else "date"
    value_col = "normal" if normals else "value"
    if dry_run:
        return len(rows)
    conn.executemany(
        f"""INSERT OR REPLACE INTO {table}
            (region_type, region, weight_basis, degree_type, {date_col}, {value_col}, fetched_at)
            VALUES (?,?,?,?,?,?,?)""",
        [(rt, region_name(rt, rid), wb, dt, dk, val, now) for rt, rid, wb, dt, dk, val in rows],
    )
    return len(rows)


def region_name(region_type: str, rid: str) -> str:
    """Normalize region identifiers: census divisions keep their ID but we
    store the well-known name alongside via convention '<id>|<name>'."""
    if region_type == "census_division" and rid in CENSUS_DIVISIONS:
        return f"{rid}|{CENSUS_DIVISIONS[rid]}"
    return rid


def collect_file(stem: str, wb: str, dt: str, rt: str, path: str):
    """Fetch one CPC file; return flat rows (region_type, rid, wb, dt, key, val)."""
    url = f"{BASE}/{path}/{stem}.txt"
    text = _fetch(url)
    if text is None:
        logger.warning(f"  miss ({path}) {stem}: HTTP error")
        return []
    rows = []
    for rid, dk, val in parse_dd_file(text):
        region_type = rt
        if rt == "states_conus":
            region_type = "conus" if rid.upper() == "US" else "state"
        rows.append((region_type, rid, wb, dt, dk, val))
    logger.info(f"  {path}/{stem}: {len(rows)} cells")
    return rows


def main():
    parser = argparse.ArgumentParser(description="NOAA CPC degree-days ingestion")
    parser.add_argument("--start-year", type=int, default=1981)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--full", action="store_true", help="re-backfill all history even if meta says done"
    )
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH) if not args.dry_run else None
    if conn:
        ensure_tables(conn)

    total = 0
    this_year = datetime.now().year

    # 1. Normals (once)
    have_normals = (
        False
        if conn is None
        else (conn.execute("SELECT COUNT(*) FROM noaa_dd_normals").fetchone()[0] > 0)
    )
    if args.full or not have_normals:
        logger.info("Fetching 1981-2010 climatology normals...")
        for stem, wb, dt, rt in FILES:
            rows = collect_file(stem, wb, dt, rt, "climatology/1981-2010")
            total += write_rows(conn, rows, normals=True, dry_run=args.dry_run)
    else:
        logger.info("Normals already present - skipping")

    # 2. Historical years (up to last complete year)
    done_year = None if conn is None else get_meta(conn, "noaa_cpc_backfill_year")
    start = args.start_year if (args.full or done_year is None) else int(done_year) + 1
    for yr in range(start, this_year):
        logger.info(f"Backfilling year {yr}...")
        year_rows = []
        for stem, wb, dt, rt in FILES:
            year_rows.extend(collect_file(stem, wb, dt, rt, str(yr)))
        total += write_rows(conn, year_rows, dry_run=args.dry_run)
        if conn and year_rows:
            set_meta(conn, "noaa_cpc_backfill_year", str(yr))

    # 3. Current year + latest mirror (always refresh)
    logger.info(f"Refreshing current year {this_year}...")
    cur_rows = []
    for stem, wb, dt, rt in FILES:
        for sub in (str(this_year), "latest"):
            cur_rows.extend(collect_file(stem, wb, dt, rt, sub))
    total += write_rows(conn, cur_rows, dry_run=args.dry_run)
    if conn:
        set_meta(conn, "noaa_cpc_last_refresh", datetime.now().isoformat(timespec="seconds"))
        conn.close()

    logger.info(
        f"Ingestion complete: {total} cells written ({'DRY RUN' if args.dry_run else 'saved'})"
    )
    return total


if __name__ == "__main__":
    sys.exit(0 if main() > 0 else 1)
