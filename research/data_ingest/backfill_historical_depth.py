"""
Historical backfill for three sources needed for the 2008 OMD pilot:
  1. FRED macro series -- WTI crude and others back to 2000-01-01
  2. EIA storage -- Lower-48 weekly storage back to 1994 (EIA series starts there)
  3. EIA production -- US Dry Production (FPD) back to 1997

These three tables were found during the data audit to have depth gaps
that block the 2008 GFC precursor window (2005-2007):
  - fred_macro (wti): only back to 2024-08-06 in the database
  - eia_storage: only back to 2014-08-08 (the live ingester correctly
    uses the API with duoarea='R48', but this backfill uses the same
    pattern against the full historical series)
  - eia_production: already back to 1997, included here for completeness
    and to verify nothing regressed

The existing backfill_fred_eia.py script had two problems:
  1. START_DATE='2015-01-01' -- too shallow for the 2005-2007 pilot window
  2. EIA storage used rngwhhd.txt (Henry Hub spot price, wrong series) --
     should be the EIA v2 API with duoarea='R48', matching ingest_eia.py

Run from C:\\Users\\legot\\Metis:
    python research/data_ingest/backfill_historical_depth.py
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.append(str(Path(__file__).resolve().parents[2]))
from research.common import runtime_config as rc

load_dotenv()
DB_URL = rc.get_db_url()
FRED_API_KEY = os.getenv("FRED_API_KEY")
EIA_API_KEY = os.getenv("EIA_API_KEY")

# Back to 2000 -- covers the full 2000-2001 Western Energy Crisis and
# well before the 2005-2007 2008-GFC precursor window.
START_DATE = "2000-01-01"

FRED_SERIES = {
    "wti_crude_price": "DCOILWTICO",
    "cpi_energy": "CPILEGSL",
    "retail_gas_price": "GASREGCOVW",
    "industrial_production": "INDPRO",
    "housing_starts": "HOUST",
    "personal_consumption": "PCE",
}


def ensure_unique_indexes(engine):
    """Ensure EIA tables have unique constraints so ON CONFLICT DO NOTHING works."""
    with engine.begin() as conn:
        # Add this new FRED index
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_fred_macro_ts_sid ON fred_macro(timestamp, series_id)"
            )
        )
        conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS idx_eia_storage_ts ON eia_storage(timestamp)")
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_eia_production_ts ON eia_production(timestamp)"
            )
        )


def fetch_fred_series(series_id: str, start: str) -> pd.DataFrame:
    """Fetch one FRED series from start_date to today."""
    resp = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "observation_start": start,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "observations" not in data or not data["observations"]:
        print(f"  {series_id}: no observations returned")
        return pd.DataFrame()
    df = pd.DataFrame(data["observations"])
    df["timestamp"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df[df["value"].notna()][["timestamp", "value"]].copy()
    print(
        f"  {series_id}: {len(df)} rows ({df['timestamp'].min().date()} to {df['timestamp'].max().date()})"
    )
    return df


def backfill_fred(engine):
    if not FRED_API_KEY:
        print("FRED_API_KEY not set -- skipping")
        return

    print("\n--- FRED backfill ---")
    for col_name, series_id in FRED_SERIES.items():
        df = fetch_fred_series(series_id, START_DATE)
        if df.empty:
            continue

        with engine.begin() as conn:
            # Check what's already in the table for this series
            existing = conn.execute(
                text(
                    "SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM fred_macro "
                    "WHERE series_id = :sid"
                ),
                {"sid": series_id},
            ).fetchone()
            print(f"    Existing in DB: {existing[0]} to {existing[1]} ({existing[2]} rows)")

            # Upsert -- same last-write-wins policy as everything else this session
            for _, row in df.iterrows():
                conn.execute(
                    text("""
                    INSERT INTO fred_macro (timestamp, series_id, value)
                    VALUES (:ts, :sid, :val)
                    ON CONFLICT(timestamp, series_id) DO UPDATE SET value=excluded.value
                """),
                    {
                        "ts": row["timestamp"].strftime("%Y-%m-%d 00:00:00.000000"),
                        "sid": series_id,
                        "val": float(row["value"]),
                    },
                )

        print(f"    Upserted {len(df)} rows for {series_id}")


import os


def backfill_eia_storage_legacy(engine):
    """
    Parses the legacy 3-region EIA archive Excel file and upserts the
    Total Lower 48 data for 1993-2009.
    """
    file_path = "data/archngshistory.xls"

    if not os.path.exists(file_path):
        print(f"\n[!] Legacy archive not found at {file_path}")
        print("    Please save the EIA history file as 'data/archngshistory.xls' and run again.")
        return

    print("\n--- EIA legacy storage archive backfill ---")

    # Read the first sheet of the Excel file. The EIA preamble is 7 rows long.
    df = pd.read_excel(file_path, sheet_name=0, skiprows=7)

    # Find the Date and Total Lower 48 columns.
    date_col = "Week ending" if "Week ending" in df.columns else df.columns[0]
    total_col = "Total Lower 48" if "Total Lower 48" in df.columns else df.columns[7]

    df = df.rename(columns={date_col: "timestamp", total_col: "storage_bcf"})
    df = df[["timestamp", "storage_bcf"]].dropna()

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["storage_bcf"] = pd.to_numeric(df["storage_bcf"], errors="coerce")
    df = df.dropna()

    # We only need the missing 1993-2009 data to bridge the gap
    df = df[df["timestamp"] < "2010-01-01"]

    if df.empty:
        print("  No legacy data found matching the criteria.")
        return

    with engine.begin() as conn:
        for _, row in df.iterrows():
            conn.execute(
                text("""
                INSERT INTO eia_storage (timestamp, storage_bcf, "area-name")
                VALUES (:ts, :val, 'NA')
                ON CONFLICT DO NOTHING
            """),
                {
                    "ts": row["timestamp"].strftime("%Y-%m-%d 00:00:00.000000"),
                    "val": float(row["storage_bcf"]),
                },
            )

    print(
        f"  Upserted {len(df)} legacy EIA storage rows ({df['timestamp'].min().date()} to {df['timestamp'].max().date()})"
    )


def fetch_eia_storage_historical(start_year: int) -> pd.DataFrame:
    """
    Fetch full EIA storage history using the same v2 API + duoarea='R48' filter
    that the fixed ingest_eia.py uses -- not the legacy .txt endpoint that
    backfill_fred_eia.py was incorrectly hitting (that was the Henry Hub spot
    price series, not storage volumes).
    """
    url = "https://api.eia.gov/v2/natural-gas/stor/wkly/data/"
    params = {
        "api_key": EIA_API_KEY,
        "frequency": "weekly",
        "data[0]": "value",
        "facets[duoarea][]": "R48",
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "length": 5000,
        "start": f"{start_year}-01-01",
    }
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    records = data["response"]["data"]
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["period"])
    df = df.rename(columns={"value": "storage_bcf"})
    df["storage_bcf"] = pd.to_numeric(df["storage_bcf"], errors="coerce")
    df = df[df["storage_bcf"].notna()][["timestamp", "storage_bcf"]].copy()
    print(
        f"  EIA storage: {len(df)} rows ({df['timestamp'].min().date()} to {df['timestamp'].max().date()})"
    )
    return df


def backfill_eia_storage(engine):
    if not EIA_API_KEY:
        print("EIA_API_KEY not set -- skipping")
        return

    print("\n--- EIA storage backfill ---")
    # EIA weekly storage data is available from 1994-01-07
    df = fetch_eia_storage_historical(start_year=1994)
    if df.empty:
        print("  No data returned")
        return

    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM eia_storage")
        ).fetchone()
        print(f"  Existing in DB: {existing[0]} to {existing[1]} ({existing[2]} rows)")

        # area-name is 'NA' for R48 aggregate (confirmed expected behavior)
        for _, row in df.iterrows():
            conn.execute(
                text("""
                INSERT INTO eia_storage (timestamp, storage_bcf, "area-name")
                VALUES (:ts, :val, 'NA')
                ON CONFLICT DO NOTHING
            """),
                {
                    "ts": row["timestamp"].strftime("%Y-%m-%d 00:00:00.000000"),
                    "val": float(row["storage_bcf"]),
                },
            )

    print(f"  Upserted {len(df)} EIA storage rows")


def fetch_eia_production_historical() -> pd.DataFrame:
    """
    Fetch full EIA dry production history using same duoarea='NUS' + process='FPD'
    filter that the fixed ingest_eia.py uses. Already goes back to 1997 in the
    DB but included here to fill any gaps and verify no regression.
    """
    url = "https://api.eia.gov/v2/natural-gas/prod/sum/data/"
    params = {
        "api_key": EIA_API_KEY,
        "frequency": "monthly",
        "data[0]": "value",
        "facets[duoarea][]": "NUS",
        "facets[process][]": "FPD",
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "length": 1000,
    }
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    records = data["response"]["data"]
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["period"])
    df = df.rename(columns={"value": "production_mmcf"})
    df["production_mmcf"] = pd.to_numeric(df["production_mmcf"], errors="coerce")
    df = df[df["production_mmcf"].notna()][["timestamp", "production_mmcf"]].copy()
    print(
        f"  EIA production: {len(df)} rows ({df['timestamp'].min().date()} to {df['timestamp'].max().date()})"
    )
    return df


def backfill_eia_production(engine):
    if not EIA_API_KEY:
        print("EIA_API_KEY not set -- skipping")
        return

    print("\n--- EIA production backfill ---")
    df = fetch_eia_production_historical()
    if df.empty:
        print("  No data returned")
        return

    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM eia_production")
        ).fetchone()
        print(f"  Existing in DB: {existing[0]} to {existing[1]} ({existing[2]} rows)")

        for _, row in df.iterrows():
            conn.execute(
                text("""
                INSERT INTO eia_production (timestamp, production_mmcf)
                VALUES (:ts, :val)
                ON CONFLICT DO NOTHING
            """),
                {
                    "ts": row["timestamp"].strftime("%Y-%m-%d 00:00:00.000000"),
                    "val": float(row["production_mmcf"]),
                },
            )

    print(f"  Upserted {len(df)} EIA production rows")


def verify(engine):
    print("\n--- Post-backfill verification ---")
    with engine.connect() as conn:
        checks = {
            # Updated to query the series_id column properly
            "fred_macro (wti)": "SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM fred_macro WHERE wti_crude_price IS NOT NULL",
            "eia_storage": "SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM eia_storage",
            "eia_production": "SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM eia_production",
        }
        for name, q in checks.items():
            row = conn.execute(text(q)).fetchone()
            print(f"  {name}: {str(row[0])[:10]} to {str(row[1])[:10]} ({row[2]:,} rows)")


def main():
    engine = create_engine(DB_URL)
    ensure_unique_indexes(engine)

    # Check existing fred_macro schema -- the upsert assumes a series_id column
    # which the current schema may not have (it was a wide table in some versions)
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(fred_macro)")).fetchall()]
        print(f"fred_macro columns: {cols}")

    if "value" not in cols:
        print(
            "\nWARNING: fred_macro has no 'value' column -- it's a wide table (one column per series)."
        )
        print("The FRED upsert below will use the wide-table approach instead.")
        backfill_fred_wide(engine, cols)
    else:
        backfill_fred(engine)

    backfill_eia_storage(engine)
    backfill_eia_storage_legacy(engine)
    backfill_eia_production(engine)
    verify(engine)


def backfill_fred_wide(engine, existing_cols):
    """
    Fallback for the wide fred_macro table layout (one column per series,
    no series_id column) -- matches what engineer_features.py actually reads.
    """
    if not FRED_API_KEY:
        print("FRED_API_KEY not set -- skipping")
        return

    print("\n--- FRED backfill (wide table) ---")
    series_to_col = {v: k for k, v in FRED_SERIES.items()}

    for series_id, col_name in series_to_col.items():
        if col_name not in existing_cols:
            print(f"  {col_name} not in fred_macro schema -- skipping")
            continue

        df = fetch_fred_series(series_id, START_DATE)
        if df.empty:
            continue

        with engine.begin() as conn:
            for _, row in df.iterrows():
                ts = row["timestamp"].strftime("%Y-%m-%d 00:00:00.000000")
                val = float(row["value"])
                exists = conn.execute(
                    text("SELECT COUNT(*) FROM fred_macro WHERE timestamp=:ts"), {"ts": ts}
                ).scalar()
                if exists:
                    conn.execute(
                        text(f"UPDATE fred_macro SET {col_name}=:val WHERE timestamp=:ts"),
                        {"val": val, "ts": ts},
                    )
                else:
                    conn.execute(
                        text(f"INSERT INTO fred_macro (timestamp, {col_name}) VALUES (:ts, :val)"),
                        {"ts": ts, "val": val},
                    )

        print(f"    Done: {col_name} ({series_id})")


if __name__ == "__main__":
    main()
