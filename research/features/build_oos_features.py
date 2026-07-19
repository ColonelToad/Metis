"""
Build the Feb-July 2026 OOS feature set for frozen-model inference.

Bridges the stale ng_futures_daily table (dead since 2026-01-08) with
cme_futures_daily's natural_gas (NG=F) series for the OOS window, since we
confirmed the two sources agree to full float precision on overlapping dates
(2026-01-02 to 2026-01-07) -- safe to stitch.

Reuses the real FeatureEngineer class (with the PPI merge_asof fix already
applied) so every derived feature -- rolling returns, volatility, EIA/FRED/PPI
merges -- is computed by the exact same code path as training, not
reimplemented and risking subtle drift.

Run this from C:\\Users\\legot\\Metis (so the relative data/ paths resolve):
    python research/features/build_oos_features.py

Outputs three parquet files to data/features/oos/:
    oos_daily_features.parquet
    oos_low_freq_features.parquet
    oos_sparse_features.parquet
covering 2025-12-01 through the current max date (buffer of >20 trading days
before the true 2026-01-09 OOS start, so lookback=20 sequences are valid from
the first real OOS row).
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

# Make research/ importable regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

from features.engineer_features import FeatureEngineer, DB_URL

BUFFER_START = "2025-12-01"  # >20 trading days before 2026-01-09, safety margin
OUTPUT_DIR = Path("data/features/oos")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


class BridgedFeatureEngineer(FeatureEngineer):
    """Overrides only price loading to bridge ng_futures_daily -> cme_futures_daily(NG=F)."""

    def load_price_data(self) -> pd.DataFrame:
        engine = self.engine

        # Primary source: ng_futures_daily, as-is, up to its max date
        with engine.connect() as conn:
            ng = pd.read_sql(
                text("SELECT date, open, high, low, close, volume FROM ng_futures_daily "
                     "WHERE date >= :start_date ORDER BY date"),
                conn, params={"start_date": self.start_date.isoformat()},
            )
        ng["date"] = pd.to_datetime(ng["date"]).dt.normalize()
        ng_max_date = ng["date"].max()
        print(f"[BRIDGE] ng_futures_daily: {ng['date'].min()} to {ng_max_date} ({len(ng)} rows)")

        # Bridge source: cme_futures_daily, natural_gas contract, dates after ng_futures_daily's max
        with engine.connect() as conn:
            cme_ng = pd.read_sql(
                text("SELECT date, open, high, low, close, volume FROM cme_futures_daily "
                     "WHERE contract_type = 'natural_gas' AND date > :cutoff ORDER BY date"),
                conn, params={"cutoff": ng_max_date.isoformat()},
            )
        cme_ng["date"] = pd.to_datetime(cme_ng["date"], format="ISO8601").dt.normalize()

        # Confirmed duplicate rows per date (two timestamp serializations of the same day) --
        # dedupe before anything else touches this.
        n_before = len(cme_ng)
        cme_ng = cme_ng.drop_duplicates(subset="date", keep="first").sort_values("date")
        n_after = len(cme_ng)
        print(f"[BRIDGE] cme_futures_daily(natural_gas) bridge: {cme_ng['date'].min()} to "
              f"{cme_ng['date'].max()} ({n_after} unique rows, deduped from {n_before})")

        df = pd.concat([ng, cme_ng], ignore_index=True).sort_values("date").reset_index(drop=True)

        # From here down: identical to FeatureEngineer.load_price_data()
        df["log_return"] = np.log(df["close"] / df["close"].shift(1))
        df["return_1d"] = df["log_return"]
        df["return_5d"] = df["log_return"].rolling(5).sum().shift(1)
        df["return_20d"] = df["log_return"].rolling(20).sum().shift(1)
        df["volatility_20d"] = df["log_return"].rolling(20).std() * np.sqrt(252)
        df["volatility_5d"] = df["log_return"].rolling(5).std() * np.sqrt(252)
        df["price_range"] = (df["high"] - df["low"]) / df["close"]
        df["momentum_20d"] = (df["close"] - df["close"].shift(20)) / df["close"].shift(20)
        df["volume_ma_20d"] = df["volume"].rolling(20).mean()
        df["volume_ratio"] = df["volume"] / (df["volume_ma_20d"] + 1e-8)

        print(f"[BRIDGE] Combined price series: {df['date'].min()} to {df['date'].max()} ({len(df)} rows)")
        return df


def main():
    print(f"[OOS] DB_URL={DB_URL}")
    eng = BridgedFeatureEngineer(DB_URL, start_date="2015-01-01")
    full_df = eng.engineer_features()

    split = eng.split_features_by_frequency()

    for name, freq_df in split.items():
        windowed = freq_df[freq_df["date"] >= BUFFER_START].reset_index(drop=True)
        
        # 1. Force the path to be absolute based on the current script location
        root_dir = Path(__file__).parent.parent.parent 
        abs_out_dir = root_dir / "data" / "features" / "oos"
        abs_out_dir.mkdir(parents=True, exist_ok=True)
        
        abs_out_path = abs_out_dir / f"oos_{name}_features.parquet"
        
        # 2. Save using the absolute path
        windowed.to_parquet(abs_out_path, index=False)
        
        # 3. Print the absolute path and instantly verify if it exists
        print(f"[OOS] Saved {name}: {windowed.shape}")
        print(f"[DEBUG] Target Path: {abs_out_path}")
        print(f"[DEBUG] Did Python actually write it? {abs_out_path.exists()}")

    # Sanity check: report PPI populated-row count post-fix, since that was the last bug found
    ppi_cols = [c for c in split["low_freq"].columns if c.startswith("ppi_index_")]
    if ppi_cols:
        windowed_lf = split["low_freq"][split["low_freq"]["date"] >= BUFFER_START]
        pct = windowed_lf[ppi_cols[0]].notna().mean() * 100
        print(f"[OOS] Sanity check -- {ppi_cols[0]} populated in OOS window: {pct:.1f}% of rows")


if __name__ == "__main__":
    main()
