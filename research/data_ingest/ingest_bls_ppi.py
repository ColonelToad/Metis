"""
Bureau of Labor Statistics (BLS) Producer Price Index (PPI) Ingestion
Fetches PPI data for energy-related industries to track cost inflation.

Signal: Cost inflation → Activity levels causality
- PPI (Inputs) ↑ → Producer margins compress → Activity decreases
- PPI (Energy) ↑ → Energy costs rise → Future price increases expected
- Lead indicator: PPI typically leads economic activity by 2-3 months

Data: BLS PPI for crude petroleum, natural gas, petroleum refining,
and natural gas distribution.
API: BLS Public Data API (free, requires registration for bulk data)

Series IDs verified against the live API on 2026-11-03. The previous IDs
(PCUOMPU, PUEUUUI01, PUEMUUI) do not exist at BLS; every request returned
"Invalid Series", and the old code silently substituted a synthetic ramp.
REAL mode must never write invented observations: a failed fetch now raises
and the ingester is marked failed.
"""

import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import List

import pandas as pd
import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Add project root for imports
sys.path.append(str(Path(__file__).resolve().parents[1]))
from research.common import runtime_config as rc

load_dotenv()
DB_URL = rc.get_db_url()
BLS_API_KEY = os.getenv("BLS_API_KEY", "")

BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data"

# BLS series IDs for energy-related PPI, verified live 2026-11-03.
# WPU = commodity index (1982=100); PCU = industry-product index (2016=100).
# Bases differ, so compare each series to itself (YoY), never levels across series.
PPI_SERIES = {
    "WPU0561": "PPI - Crude petroleum (WPU0561)",
    "WPU0531": "PPI - Natural gas (WPU0531)",
    "PCU3241103241101": "PPI - Petroleum refining (NAICS 3241)",
    "PCU221210221210": "PPI - Natural gas distribution (NAICS 2211)",
}


class BLSFetchError(RuntimeError):
    """Raised when the BLS API yields no usable data in REAL mode."""


def fetch_ppi_data(series_ids: List[str]) -> pd.DataFrame:
    """
    Fetch PPI data from BLS API.

    Args:
        series_ids: List of BLS series IDs (e.g., ["WPU0561", "WPU0531"])

    Returns:
        DataFrame with date, series_id, series_name, ppi_index

    Raises:
        BLSFetchError: no API key, or no series returned any observations.
    """
    if not BLS_API_KEY:
        raise BLSFetchError("BLS_API_KEY is not set - refusing to fabricate PPI data")

    all_data = []
    errors = []

    for series_id in series_ids:
        try:
            payload = {
                "seriesid": [series_id],
                "startyear": 2015,
                "endyear": datetime.now().year,
                "registrationkey": BLS_API_KEY,
            }

            response = requests.post(BLS_API_URL, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()

            if result.get("status") != "REQUEST_SUCCEEDED":
                msg = result.get("message", "Unknown error")
                print(f"[BLS] API error for {series_id}: {msg}")
                errors.append(f"{series_id}: {msg}")
                continue

            series_data = result.get("Results", {}).get("series", [])
            if not series_data:
                print(f"[BLS] No data for series {series_id}")
                errors.append(f"{series_id}: no series in response")
                continue

            # The API reports per-series problems in `message` while still
            # returning REQUEST_SUCCEEDED; surface them instead of hiding them.
            for msg in result.get("message") or []:
                print(f"[BLS] {series_id}: {msg}")

            series_name = PPI_SERIES.get(series_id, series_id)
            for series in series_data:
                for point in series.get("data", []):
                    try:
                        year = int(point.get("year", 0))
                        # BLS uses period M01..M12 for months, M13 for annual.
                        period = str(point.get("period", ""))
                        if period == "M13":
                            continue  # annual average, not a monthly observation
                        month = int(period.lstrip("M") or 0)
                        if not (1 <= month <= 12):
                            continue
                        value = float(point.get("value", 0))

                        all_data.append(
                            {
                                "date": date(year, month, 1),
                                "series_id": series_id,
                                "series_name": series_name,
                                "ppi_index": value,
                            }
                        )
                    except (ValueError, TypeError):
                        continue

        except Exception as e:
            print(f"[BLS] Fetch error for {series_id}: {e}")
            errors.append(f"{series_id}: {e}")

    if not all_data:
        raise BLSFetchError("BLS returned no observations for any series: " + "; ".join(errors))

    df = pd.DataFrame(all_data)
    df = df.sort_values(["series_id", "date"])

    missing = set(series_ids) - set(df["series_id"].unique())
    if missing:
        print(f"[BLS] WARNING: no data for {sorted(missing)}")

    print(f"[BLS] Fetched {len(df)} PPI records from {df['series_id'].nunique()} series")
    return df


def calculate_yoy_change(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate year-over-year % change in PPI.

    Signal interpretation:
    - PPI ↑ >3% YoY → Cost inflation → Margin compression → Activity suppression (in 2-3 months)
    """
    df = df.copy()
    df = df.sort_values(["series_id", "date"])

    # Group by series and calculate YoY
    for series_id in df["series_id"].unique():
        mask = df["series_id"] == series_id
        df.loc[mask, "ppi_yoy_change"] = df.loc[mask, "ppi_index"].pct_change(periods=12) * 100

    return df


def ensure_table(engine) -> None:
    """Create bls_ppi table if not exists."""
    create_sql = """
    CREATE TABLE IF NOT EXISTS bls_ppi (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date DATE NOT NULL,
        series_id TEXT NOT NULL,
        series_name TEXT,
        ppi_index REAL NOT NULL,
        ppi_yoy_change REAL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(date, series_id)
    );
    CREATE INDEX IF NOT EXISTS idx_bls_ppi_date ON bls_ppi(date);
    CREATE INDEX IF NOT EXISTS idx_bls_ppi_series ON bls_ppi(series_id);
    """
    with engine.begin() as conn:
        for sql in create_sql.split(";"):
            if sql.strip():
                conn.execute(text(sql))
    print("[BLS] Table ensured: bls_ppi")


def upsert_ppi(engine, df: pd.DataFrame) -> int:
    """Replace each series' history with the freshly fetched observations."""
    if df.empty:
        print("[BLS] No PPI data to upsert")
        return 0

    ensure_table(engine)

    df_insert = df.copy()
    df_insert["timestamp"] = datetime.now().isoformat()

    # Replace per series rather than append: BLS revises prior months, and the
    # old append-only path duplicated every month's observations on each run.
    # One transaction, so a failure cannot leave a series half-deleted.
    with engine.begin() as conn:
        for series_id in df_insert["series_id"].unique():
            conn.execute(text("DELETE FROM bls_ppi WHERE series_id = :sid"), {"sid": series_id})
        df_insert.to_sql("bls_ppi", conn, if_exists="append", index=False, method="multi")

    print(
        f"[BLS] Wrote {len(df_insert)} PPI records across {df_insert['series_id'].nunique()} series"
    )
    return len(df_insert)


def main() -> int:
    """Main ingestion pipeline. Returns rows written."""
    rc.log_mode("BLS Producer Price Index")

    # Skip database writes in DEV mode - DEV mode is read-only
    if not rc.require_real_mode("BLS PPI ingestion"):
        print("[BLS] Skipping ingestion in DEV mode (read-only)")
        return 0

    # Fetch PPI data for key energy series. Raises if BLS returns nothing --
    # REAL mode does not fall back to invented values.
    df = fetch_ppi_data(list(PPI_SERIES.keys()))

    # Calculate YoY changes
    df = calculate_yoy_change(df)

    # Save to database
    engine = create_engine(DB_URL)
    written = upsert_ppi(engine, df)

    # Log summary by series
    print("\n[BLS] Latest PPI by series:")
    latest_by_series = df.groupby("series_id").tail(1)
    for _, row in latest_by_series.iterrows():
        yoy_str = f"{row['ppi_yoy_change']:+.1f}%" if pd.notna(row["ppi_yoy_change"]) else "N/A"
        print(f"  {row['series_name']}: {row['ppi_index']:.1f} (YoY: {yoy_str})")

    return written


if __name__ == "__main__":
    main()
