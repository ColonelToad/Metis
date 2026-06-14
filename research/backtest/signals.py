"""
EIA injection-surprise signal aligned to NG futures trade dates.

EIA schedule:
  - DB timestamp = week-ending Friday (EIA API "period" field)
  - Report is published Thursday morning (timestamp - 1 business day)
  - We can enter at Friday open = the week-ending date in the DB

Signal:
  injection_surprise_z = (actual_injection - seasonal_avg) / trailing_52w_std
  Long when z < -threshold  (less storage than expected -> bullish)
  Short when z > +threshold (more storage than expected -> bearish)
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "metis.db"


def load_ng_prices() -> pd.DataFrame:
    """NG front-month daily OHLCV. SQLite through 2026-01-08, yfinance fills forward."""
    conn = sqlite3.connect(DB_PATH)
    sq = pd.read_sql(
        "SELECT date, open, high, low, close, volume FROM ng_futures_daily ORDER BY date",
        conn,
        parse_dates=["date"],
    ).set_index("date")
    conn.close()

    sq.index = sq.index.tz_localize(None)
    cutoff = sq.index[-1]

    # Fill gap from SQLite cutoff to today via yfinance
    yf_start = (cutoff + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    yf_raw = yf.download("NG=F", start=yf_start, progress=False, auto_adjust=True)
    if not yf_raw.empty:
        yf_raw.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in yf_raw.columns]
        yf_raw.index = yf_raw.index.tz_localize(None)
        yf_raw = yf_raw[["open", "high", "low", "close", "volume"]]
        prices = pd.concat([sq, yf_raw]).sort_index()
    else:
        prices = sq

    prices = prices[~prices.index.duplicated(keep="last")]
    prices = prices.dropna(subset=["close"])
    return prices


def load_eia_signal(threshold: float = 0.5) -> pd.DataFrame:
    """
    Returns weekly rows with columns:
      trade_date       — Friday to enter (= EIA week-ending timestamp)
      injection        — bcf injected that week
      surprise         — injection - seasonal_avg
      surprise_z       — surprise / trailing_52w_std
      signal           — 1 (long), -1 (short), 0 (no trade)
    """
    conn = sqlite3.connect(DB_PATH)
    raw = pd.read_sql(
        """SELECT timestamp AS date, MAX(CAST(storage_bcf AS REAL)) AS storage_bcf
           FROM eia_storage
           GROUP BY timestamp
           ORDER BY date""",
        conn,
        parse_dates=["date"],
    )
    conn.close()

    df = raw.set_index("date").sort_index()
    df.index = df.index.tz_localize(None)

    # Injection = week-over-week change in storage
    df["injection"] = df["storage_bcf"].diff()
    df["week_of_year"] = df.index.isocalendar().week.astype(int)

    # Seasonal average: expanding historical mean per calendar week, shifted 1 (no look-ahead)
    df["seasonal_avg"] = df.groupby("week_of_year")["injection"].transform(
        lambda x: x.expanding().mean().shift(1)
    )
    df["surprise"] = df["injection"] - df["seasonal_avg"]

    # Normalise by trailing 52-week std (shift 1 to avoid look-ahead)
    df["surprise_std"] = df["surprise"].rolling(52, min_periods=26).std().shift(1)
    df["surprise_z"] = df["surprise"] / df["surprise_std"].replace(0, np.nan)

    # Signal direction
    df["signal"] = 0
    df.loc[df["surprise_z"] < -threshold, "signal"] = 1   # long (bullish surprise)
    df.loc[df["surprise_z"] > threshold, "signal"] = -1   # short (bearish surprise)

    df = df.dropna(subset=["surprise_z"])

    return df[["injection", "surprise", "surprise_z", "signal"]].rename_axis("trade_date")
