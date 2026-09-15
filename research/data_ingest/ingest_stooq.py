"""
Stock Market Data Ingestion using Stooq

Rewritten from the original if_exists='replace' + rolling-730-day-window
version, which meant the table could never accumulate real history -- every
run discarded anything older than 730 days before that run's execution time,
regardless of how long the project had been collecting data.

This version:
  - Fetches full history (since 2015, matching the rest of Metis's data range)
    rather than a rolling window, so there's no artificial truncation.
  - Upserts on (timestamp, ticker) instead of replacing the whole table, so
    reruns are safe and idempotent rather than destructive.
  - Logs each ticker's success/failure explicitly rather than silently
    swallowing failures in a bare except -- this is how CHK's failure went
    unnoticed in the original version.

On conflict resolution: a same-(timestamp, ticker) conflict is expected to
occur legitimately, not just from a bug -- stock splits, dividends, and
vendor corrections all cause a historical bar's reported values to change
after the fact, even though the calendar date it's attached to doesn't move.
Last-write-wins (DO UPDATE) is the correct policy here: a newer fetch
reflects a more complete, more current view of that date, not a competing
claim about what "really" happened.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pandas_datareader.data as web
import yfinance as yf
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.append(str(Path(__file__).resolve().parents[2]))
from research.common import runtime_config as rc

load_dotenv()
DB_URL = rc.get_db_url()

START_DATE = os.getenv("STOCK_PRICES_START_DATE", "2015-01-01")

# Energy-related stocks (natural gas, LNG, pipelines, utilities).
# CHK was dropped: 2020 bankruptcy + 2024 Southwestern merger -> EXE
# (Expand Energy, listed from 2024-10-02). Lineage in ticker_lineage.
ENERGY_TICKERS = {
    # Natural Gas & LNG
    "EXE": "Expand Energy",
    "EQT": "EQT Corporation",
    "AR": "Antero Resources",
    "CNX": "CNX Resources",
    "RRC": "Range Resources",
    "CQP": "Cheniere Energy Partners",  # LNG exporter
    # Integrated Majors
    "XOM": "Exxon Mobil",
    "CVX": "Chevron",
    "COP": "ConocoPhillips",
    # Refiners
    "MPC": "Marathon Petroleum",
    "VLO": "Valero Energy",
    # Energy Services
    "SLB": "Schlumberger",
    "HAL": "Halliburton",
    # Pipelines & Midstream
    "KMI": "Kinder Morgan",
    "WMB": "Williams Companies",
    "EPD": "Enterprise Products",
    "ET": "Energy Transfer",
    "OKE": "ONEOK",
    # Utilities with Gas Exposure
    "NEE": "NextEra Energy",
    "D": "Dominion Energy",
    "SO": "Southern Company",
    "DUK": "Duke Energy",
    # ETFs
    "XLE": "Energy Select Sector",
    "UNG": "US Natural Gas Fund",
    "FCG": "First Trust Natural Gas ETF",
    "XOP": "SPDR S&P Oil & Gas",
}


def fetch_stock_data(ticker, start_date, end_date):
    """Fetch historical stock data from Yahoo Finance"""
    if not rc.require_real_mode(f"Yahoo {ticker}"):
        return pd.DataFrame()

    try:
        # yfinance expects standard tickers (no .US suffix needed)
        df = yf.download(ticker, start=start_date, end=end_date, progress=False)

        if df.empty:
            return pd.DataFrame()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.sort_index()
        df["ticker"] = ticker
        # Canonical text format matches backfill_stock_prices ('%Y-%m-%d %H:%M:%S').
        # The old datetime64-list form stored microseconds text while other paths
        # wrote ns-epoch ints and NULLs -- same (ticker, day) in different formats
        # slipped past the UNIQUE index as silent duplicates (cleaned 2026-09-15:
        # 313k -> 151k rows). Keep this format stable.
        df["timestamp"] = pd.to_datetime(df.index).strftime("%Y-%m-%d %H:%M:%S").tolist()
        df = df.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )

        # yfinance includes an 'Adj Close' column, so we just select the ones we need
        return df[["timestamp", "ticker", "open", "high", "low", "close", "volume"]]
    except Exception as e:
        print(f"  FAILED: {ticker} -- {e}")
        return pd.DataFrame()


def ensure_unique_index(engine):
    """ON CONFLICT requires an actual unique constraint to target -- the
    original if_exists='replace' table never had one, since replace-based
    ingestion doesn't need it."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_prices_ts_ticker "
                "ON stock_prices(timestamp, ticker)"
            )
        )


def upsert_stock_data(df: pd.DataFrame, engine):
    if df.empty:
        return 0

    cols = ["timestamp", "ticker", "open", "high", "low", "close", "volume", "company_name"]
    for c in cols:
        if c not in df.columns:
            df[c] = None

    records = df[cols].to_dict("records")
    placeholders = ", ".join([f":{c}" for c in cols])
    update_clause = ", ".join(
        [f"{c}=excluded.{c}" for c in cols if c not in ("timestamp", "ticker")]
    )

    stmt = text(f"""
        INSERT INTO stock_prices ({', '.join(cols)})
        VALUES ({placeholders})
        ON CONFLICT(timestamp, ticker) DO UPDATE SET {update_clause}
    """)

    with engine.begin() as conn:
        conn.execute(stmt, records)

    return len(records)


def main():
    rc.log_mode("Stooq Stock Data")

    end_date = datetime.now()
    print(f"Fetching stock data from Stooq ({START_DATE} to {end_date.date()})...")

    engine = create_engine(DB_URL)
    ensure_unique_index(engine)

    total_upserted = 0
    succeeded, failed = [], []

    for ticker, company in ENERGY_TICKERS.items():
        df = fetch_stock_data(ticker, START_DATE, end_date)
        if not df.empty:
            df["company_name"] = company
            n = upsert_stock_data(df, engine)
            total_upserted += n
            succeeded.append(ticker)
            print(f"  {ticker} ({company}): {n} rows upserted")
        else:
            failed.append(ticker)

    print(f"\nSucceeded: {succeeded}")
    if failed:
        print(f"Failed (visible now, not silently dropped): {failed}")
    print(f"Total rows upserted this run: {total_upserted}")

    return total_upserted


if __name__ == "__main__":
    main()
