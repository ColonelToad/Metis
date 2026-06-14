"""
3-gate daily shock regime detector for NG futures.

Gate 1 — Statistical: daily return z-score vs trailing 60-day realized vol
  |z| > 1.5 : elevated
  |z| > 2.5 : shock candidate
  |z| > 4.0 : crisis candidate

Gate 2 — Cross-market: XLE (energy ETF) z-score + NG volume spike
  Both trigger on same day -> confirms market-wide dislocation, not noise

Gate 3 — Catalog: date falls within a known shock event window (+/- 5 days)

Final regime (daily):
  crisis   : |z| > 4.0
  shock    : |z| > 2.5 AND (gate2 OR gate3)
  elevated : |z| > 1.5
  normal   : otherwise

Backtest use: use PRIOR week's peak regime to gate EIA trades (no look-ahead).
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH   = REPO_ROOT / "data" / "metis.db"

# Thresholds (from Event.md)
Z_ELEVATED = 1.5
Z_SHOCK    = 2.5
Z_CRISIS   = 4.0

# Gate 2 triggers
VOLUME_Z_THRESHOLD = 2.0   # NG volume > 2 std above 20-day mean
XLE_Z_THRESHOLD    = 2.0   # XLE daily return > 2 std (energy sector dislocation)


def load_ng_prices(conn: sqlite3.Connection) -> pd.DataFrame:
    sq = pd.read_sql(
        "SELECT date, close, volume FROM ng_futures_daily ORDER BY date",
        conn, parse_dates=["date"],
    ).set_index("date")
    sq.index = sq.index.tz_localize(None)

    # Supplement with yfinance for dates after SQLite cutoff
    cutoff = sq.index[-1]
    yf_start = (cutoff + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    yf_raw = yf.download("NG=F", start=yf_start, progress=False, auto_adjust=True)
    if not yf_raw.empty:
        yf_raw.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in yf_raw.columns]
        yf_raw.index = yf_raw.index.tz_localize(None)
        yf_extra = yf_raw[["close", "volume"]]
        sq = pd.concat([sq[["close", "volume"]], yf_extra]).sort_index()

    sq = sq[~sq.index.duplicated(keep="last")].dropna(subset=["close"])
    return sq


def load_xle(start: str, end: str) -> pd.Series:
    """XLE daily log-returns as cross-market proxy."""
    try:
        df = yf.download("XLE", start=start, end=end, progress=False, auto_adjust=True)
        if df.empty:
            return pd.Series(dtype=float)
        close = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
        close.index = close.index.tz_localize(None)
        return np.log(close / close.shift(1)).rename("xle_return")
    except Exception:
        return pd.Series(dtype=float)


def _catalog_mask(dates: pd.DatetimeIndex, catalog: pd.DataFrame, buffer_days: int = 5) -> pd.Series:
    """Boolean Series: True if date is within any catalog event window (+ buffer)."""
    mask = pd.Series(False, index=dates)
    for _, row in catalog.iterrows():
        lo = row["start"] - pd.Timedelta(days=buffer_days)
        hi = row["end"]   + pd.Timedelta(days=buffer_days)
        mask |= (dates >= lo) & (dates <= hi)
    return mask


def compute_regimes(
    ng: pd.DataFrame,
    catalog: pd.DataFrame,
    vol_window: int = 60,
    vol_window_short: int = 20,
) -> pd.DataFrame:
    """
    Parameters
    ----------
    ng      : NG daily DataFrame with columns [close, volume]
    catalog : output of catalog.build_catalog()

    Returns
    -------
    Daily DataFrame with regime classification and gate signals.
    """
    df = ng.copy()
    df["log_return"] = np.log(df["close"] / df["close"].shift(1))

    # Gate 1 — z-score of daily return vs trailing realized vol
    rolling_std = df["log_return"].rolling(vol_window, min_periods=30).std()
    df["return_z"] = df["log_return"] / rolling_std.replace(0, np.nan)

    # Gate 2a — NG volume spike
    vol_mean = df["volume"].rolling(vol_window_short, min_periods=10).mean()
    vol_std  = df["volume"].rolling(vol_window_short, min_periods=10).std()
    df["volume_z"] = (df["volume"] - vol_mean) / vol_std.replace(0, np.nan)

    # Gate 2b — XLE cross-market
    start_str = df.index[0].strftime("%Y-%m-%d")
    end_str   = (df.index[-1] + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    xle_ret = load_xle(start_str, end_str)
    if not xle_ret.empty:
        xle_std = xle_ret.rolling(vol_window, min_periods=30).std()
        xle_z   = (xle_ret / xle_std.replace(0, np.nan)).reindex(df.index)
        df["xle_z"] = xle_z
    else:
        df["xle_z"] = np.nan

    # Gate flags
    df["gate1"] = df["return_z"].abs() > Z_ELEVATED
    df["gate2"] = (df["volume_z"] > VOLUME_Z_THRESHOLD) | (df["xle_z"].abs() > XLE_Z_THRESHOLD)
    df["gate3"] = _catalog_mask(df.index, catalog).values

    # Regime classification
    abs_z = df["return_z"].abs().fillna(0)
    regime = pd.Series("normal", index=df.index)
    regime[abs_z > Z_ELEVATED]                                        = "elevated"
    regime[(abs_z > Z_SHOCK) & (df["gate2"] | df["gate3"])]          = "shock"
    regime[abs_z > Z_CRISIS]                                          = "crisis"

    df["regime"] = regime
    df["severity"] = regime.map({"normal": 0, "elevated": 1, "shock": 2, "crisis": 3}).fillna(0).astype(int)

    return df[["log_return", "return_z", "volume_z", "xle_z", "gate1", "gate2", "gate3", "regime", "severity"]]


def rolling_peak_regime(regimes: pd.DataFrame, window_days: int = 5) -> pd.Series:
    """
    For each date, return the worst regime seen in the trailing `window_days`.
    Used by the backtest: 'was last week elevated/shock/crisis?'
    """
    order = {"normal": 0, "elevated": 1, "shock": 2, "crisis": 3}
    sev   = regimes["severity"]
    peak  = sev.rolling(window_days, min_periods=1).max()
    rev_order = {v: k for k, v in order.items()}
    return peak.map(rev_order)


def write_regimes_to_db(regimes: pd.DataFrame, conn: sqlite3.Connection) -> None:
    out = regimes.copy()
    out.index.name = "date"
    out = out.reset_index()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    # Coerce booleans for SQLite
    for col in ["gate1", "gate2", "gate3"]:
        out[col] = out[col].astype(int)
    out.to_sql("shock_regimes", conn, if_exists="replace", index=False)
    print(f"  Wrote {len(out)} daily regime rows to shock_regimes table")
    counts = regimes["regime"].value_counts()
    for regime, count in counts.items():
        pct = count / len(regimes) * 100
        print(f"    {regime:<10}: {count:>5} days ({pct:.1f}%)")
