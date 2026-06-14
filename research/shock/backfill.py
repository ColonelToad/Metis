"""
Populate shock_events and shock_regimes tables in data/metis.db.

Usage:
    python research/shock/backfill.py
    python research/shock/backfill.py --no-fema       # skip FEMA API
    python research/shock/backfill.py --since 2014    # only compute regimes from year
"""
import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from research.shock import catalog as cat_module
from research.shock import detector as det_module


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill shock catalog and regime tables")
    parser.add_argument("--no-fema", action="store_true", help="Skip FEMA API call")
    parser.add_argument("--since", type=int, default=2000, help="Start year for regime computation")
    args = parser.parse_args()

    conn = sqlite3.connect(det_module.DB_PATH)

    # ── 1. Build and write shock catalog ──────────────────────────────────────
    print("Building shock event catalog...")
    include_fema = not args.no_fema
    catalog = cat_module.build_catalog(include_fema=include_fema)
    print(f"  Total events: {len(catalog)}  (manual={len(catalog[catalog.source=='manual'])}, fema={len(catalog[catalog.source=='fema'])})")
    cat_module.write_catalog_to_db(catalog, conn)

    # ── 2. Load NG prices ─────────────────────────────────────────────────────
    print("Loading NG price data...")
    ng = det_module.load_ng_prices(conn)
    ng = ng[ng.index.year >= args.since]
    print(f"  NG prices: {ng.index[0].date()} -> {ng.index[-1].date()}  ({len(ng)} days)")

    # ── 3. Compute and write daily regimes ────────────────────────────────────
    print("Computing daily regimes (Gate 1 + Gate 2 + Gate 3)...")
    print("  Fetching XLE cross-market data...")
    regimes = det_module.compute_regimes(ng, catalog)
    det_module.write_regimes_to_db(regimes, conn)

    conn.commit()
    conn.close()
    print("\nDone. Tables updated: shock_events, shock_regimes")


if __name__ == "__main__":
    main()
