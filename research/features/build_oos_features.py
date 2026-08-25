"""
Build OOS feature windows for frozen-model inference.

Price-spine note (Aug 2026): FeatureEngineer.load_price_data now stitches
three tiers internally -- official cme_settlements > ng_futures_daily
history > cme_futures_daily Yahoo bridge -- so the old two-way bridge
override here is superseded and this script simply uses the base class.
Overlap validation: official settles vs Yahoo agreed to 0.00% mean diff on
all five products across the first week of direct collection.

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


# Kept as a named subclass for continuity with prior runs; price stitching
# now lives in the base class (see load_price_data there).
class BridgedFeatureEngineer(FeatureEngineer):
    pass


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
