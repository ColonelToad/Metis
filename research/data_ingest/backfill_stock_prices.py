"""
One-time historical backfill for stock_prices using yfinance.

The current ingester (ingest_stooq.py, now using yfinance) pulls from
START_DATE='2015-01-01' in its normal daily run. This script does a single
full-history pull back to 2000-01-01 for the OMD pilot's 2005-2007 window,
then hands off to the daily ingester for ongoing incremental updates.

The unique index on (timestamp, ticker) means re-running this is safe --
ON CONFLICT DO UPDATE last-write-wins, same as everything else this session.

Run from C:\\Users\\legot\\Metis:
    python research/data_ingest/backfill_stock_prices.py
"""
import os
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import yfinance as yf
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parents[2]))
from research.common import runtime_config as rc

load_dotenv()
DB_URL = rc.get_db_url()

START_DATE = "2000-01-01"

# Same ticker universe as ingest_stooq.py -- keeping these in sync is important.
# CHK is excluded: delisted post-merger, yfinance returns 404.
# EXE (Expand Energy) only has data from 2024-10-02 (merger date) -- included
# but will naturally return a short history, not an error.
ENERGY_TICKERS = {
    "EXE": "Expand Energy (formerly CHK, from 2024-10-02)",
    "EQT": "EQT Corporation",
    "AR":  "Antero Resources",
    "CNX": "CNX Resources",
    "RRC": "Range Resources",
    "KMI": "Kinder Morgan",
    "WMB": "Williams Companies",
    "EPD": "Enterprise Products",
    "ET":  "Energy Transfer",
    "OKE": "ONEOK",
    "NEE": "NextEra Energy",
    "D":   "Dominion Energy",
    "SO":  "Southern Company",
    "DUK": "Duke Energy",
    "XLE": "Energy Select Sector ETF",
    "UNG": "US Natural Gas Fund ETF",
    "FCG": "First Trust Natural Gas ETF",
    "XOP": "SPDR S&P Oil & Gas ETF",
}


def ensure_unique_index(engine):
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_prices_ts_ticker "
            "ON stock_prices(timestamp, ticker)"
        ))


def backfill_ticker(ticker: str, company: str, engine) -> int:
    try:
        df = yf.download(ticker, start=START_DATE, auto_adjust=True, progress=False)
        if df.empty:
            print(f"  {ticker}: no data returned (possibly listed after 2000, or delisted)")
            return 0

        df = df.reset_index()
        # yfinance returns MultiIndex columns when downloading a single ticker
        # with auto_adjust -- flatten if needed
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] if c[1] == '' else c[0] for c in df.columns]

        df = df.rename(columns={
            "Date": "timestamp",
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        })
        df["ticker"] = ticker
        df["company_name"] = company
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        keep = ["timestamp", "ticker", "company_name", "open", "high", "low", "close", "volume"]
        df = df[[c for c in keep if c in df.columns]].dropna(subset=["close"])

        # Add this line to convert timestamps to standard strings
        df["timestamp"] = df["timestamp"].dt.strftime('%Y-%m-%d %H:%M:%S')

        records = df.to_dict("records")
        cols = [c for c in keep if c in df.columns]
        placeholders = ", ".join(f":{c}" for c in cols)
        update_clause = ", ".join(
            f"{c}=excluded.{c}" for c in cols if c not in ("timestamp", "ticker")
        )

        with engine.begin() as conn:
            conn.execute(text(f"""
                INSERT INTO stock_prices ({', '.join(cols)})
                VALUES ({placeholders})
                ON CONFLICT(timestamp, ticker) DO UPDATE SET {update_clause}
            """), records)

        date_min = df["timestamp"].min()[:10]
        date_max = df["timestamp"].max()[:10]
        print(f"  {ticker}: {len(df):,} rows ({date_min} to {date_max})")
        return len(df)

    except Exception as e:
        print(f"  {ticker}: FAILED -- {e}")
        return 0


def main():
    engine = create_engine(DB_URL)
    ensure_unique_index(engine)

    print(f"Backfilling {len(ENERGY_TICKERS)} tickers from {START_DATE} to today...\n")

    total = 0
    succeeded, failed = [], []

    for ticker, company in ENERGY_TICKERS.items():
        n = backfill_ticker(ticker, company, engine)
        if n > 0:
            succeeded.append(ticker)
            total += n
        else:
            failed.append(ticker)

    print(f"\nSucceeded ({len(succeeded)}): {succeeded}")
    if failed:
        print(f"Failed ({len(failed)}): {failed}")
    print(f"Total rows upserted: {total:,}")

    # Verification
    with engine.connect() as conn:
        print("\n--- Post-backfill verification ---")
        for ticker in ["XLE", "EQT", "KMI"]:
            row = conn.execute(text(
                "SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM stock_prices WHERE ticker=:t"
            ), {"t": ticker}).fetchone()
            print(f"  {ticker}: {str(row[0])[:10]} to {str(row[1])[:10]} ({row[2]:,} rows)")


if __name__ == "__main__":
    main()
