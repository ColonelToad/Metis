"""
Bulk CSV loader for OpenStates state bills (manual-download path).

Source: openstates.org/data/session-csv archives, downloaded by hand to
data/cache/state_bills_bulk/ (git-ignored, R2-excluded). One zip per
state-session; each holds {prefix}_bills.csv + _bill_sponsorships.csv +
_bill_actions.csv (+ others we ignore).

Why bulk instead of API (Oct-2026): the v3 API free tier sustained-429s a
full-history backfill for 7.7h straight (zero rows). Bulk = ~13 downloads,
zero quota burn. The API ingester (ingest_state_bills.py) stays as the
updated_since delta path with fail-fast 429 policy.

Keeper gate reuses TITLE_KEYWORDS from ingest_state_bills (single definition).
Writes the same state_bills / state_bill_ingest_meta tables via
INSERT OR REPLACE, so bulk and API loads are interchangeable.

USAGE:
  python research/data_ingest/load_state_bills_bulk.py                 # all archives
  python research/data_ingest/load_state_bills_bulk.py --states TX,PA  # subset (abbrs)
  python research/data_ingest/load_state_bills_bulk.py --dry-run       # parse + report only

Polars-native (project default); pandas only at the sqlite boundary.
"""

import argparse
import ast
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data_ingest.ingest_state_bills import TITLE_KEYWORDS, _abbr  # noqa: E402

BULK_DIR = Path("data/cache/state_bills_bulk")
DB_PATH = "data/metis.db"

ABBR_TO_STATE = {
    "tx": "Texas", "pa": "Pennsylvania", "oh": "Ohio", "wv": "West Virginia",
    "ca": "California", "ny": "New York", "co": "Colorado", "nd": "North Dakota",
    "ia": "Iowa", "az": "Arizona",
}


def _as_json_list(raw: str) -> str:
    """Python-literal list string from CSV -> JSON array string (fallback raw)."""
    if not raw:
        return json.dumps([])
    try:
        return json.dumps(list(ast.literal_eval(raw)))
    except Exception:
        return json.dumps([raw])


def _openstates_url(abbr: str, session: str, identifier: str) -> str:
    nospace = (identifier or "").replace(" ", "")
    return f"https://openstates.org/{abbr.lower()}/bills/{session}/{nospace}/"


def load_archive(bills_csv: Path, conn=None, dry_run: bool = False) -> dict:
    """Load one session archive (bills + sponsorships + actions)."""
    stem = bills_csv.name[: -len("_bills.csv")]
    abbr = bills_csv.name.split("_")[0].lower()
    state = ABBR_TO_STATE.get(abbr, abbr.upper())
    spons_csv = bills_csv.with_name(f"{stem}_bill_sponsorships.csv")
    actions_csv = bills_csv.with_name(f"{stem}_bill_actions.csv")

    bills = (
        pl.read_csv(bills_csv, infer_schema_length=10000)
        .lazy()
        .with_columns(
            pl.col("title").fill_null(""),
            pl.col("session_identifier").cast(pl.String),
        )
        .filter(
            pl.col("title").map_elements(
                lambda t: bool(TITLE_KEYWORDS.search(t or "")),
                return_dtype=pl.Boolean,
            )
        )
        .collect()
    )
    seen = len(bills)
    if seen == 0:
        return {"state": state, "seen": 0, "kept": 0, "sessions": []}

    # Sponsor counts (left join keeps zero-sponsor bills).
    if spons_csv.exists():
        spons = (
            pl.scan_csv(spons_csv, infer_schema_length=1000)
            .group_by("bill_id")
            .agg(pl.len().cast(pl.Int64).alias("sponsor_count"))
            .collect()
        )
        bills = bills.join(spons, left_on="id", right_on="bill_id", how="left")
    if "sponsor_count" not in bills.columns:
        bills = bills.with_columns(pl.lit(0).cast(pl.Int64).alias("sponsor_count"))
    bills = bills.with_columns(pl.col("sponsor_count").fill_null(0))

    # First/latest action per bill (order column breaks date ties).
    if actions_csv.exists():
        acts = (
            pl.scan_csv(actions_csv, infer_schema_length=10000)
            .with_columns(
                # datetime-with-offset (OH/PA) vs date-only (TX): strip any
                # offset/Z suffix first (polars 1.x refuses tz-aware strings
                # without an explicit format), then parse naive.
                pl.col("date")
                .str.replace(r"([+-]\d{2}:?\d{2}|Z)$", "")
                .str.to_datetime(strict=False)
                .dt.date()
                .alias("date"),
                pl.col("order").cast(pl.Int64, strict=False).fill_null(0),
            )
            .drop_nulls(["bill_id", "date"])
            .sort(["bill_id", "date", "order"])
            .group_by("bill_id")
            .agg([
                pl.col("date").first().alias("first_action_date"),
                pl.col("date").last().alias("latest_action_date"),
                pl.col("description").last().alias("latest_action_description"),
            ])
            .collect()
        )
        bills = bills.join(acts, left_on="id", right_on="bill_id", how="left")

    rows = bills.to_dicts()
    sessions = sorted({str(r.get("session_identifier") or "") for r in rows} - {""})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    kept = 0
    if not dry_run:
        data = [
            (
                r["id"],
                state,
                str(r.get("session_identifier") or ""),
                r.get("identifier"),
                r.get("title"),
                ",".join(ast.literal_eval(r["classification"])
                         if r.get("classification") else []),
                _as_json_list(r.get("subject")),
                str(r.get("first_action_date") or "") or None,
                str(r.get("latest_action_date") or "") or None,
                r.get("latest_action_description"),
                int(r.get("sponsor_count") or 0),
                _openstates_url(abbr, r.get("session_identifier"), r.get("identifier")),
                now,
            )
            for r in rows
        ]
        conn.executemany(
            """INSERT OR REPLACE INTO state_bills
               (bill_id, jurisdiction, session, bill_number, title,
                classification, subjects, first_action_date,
                latest_action_date, latest_action_description,
                sponsor_count, source_url, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            data,
        )
        conn.execute(
            """INSERT OR REPLACE INTO state_bill_ingest_meta
               (jurisdiction, session, bills_seen, bills_kept, fetched_at)
               VALUES (?,?,?,?,?)""",
            (state, ",".join(sessions), seen, len(data), now),
        )
        conn.commit()
        kept = len(data)
    else:
        kept = len(rows)
    return {"state": state, "seen": seen, "kept": kept, "sessions": sessions}


def main() -> int:
    ap = argparse.ArgumentParser(description="Load OpenStates bulk CSV archives")
    ap.add_argument("--states", default="", help="comma-separated abbrs, e.g. TX,PA")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dir", default=str(BULK_DIR))
    args = ap.parse_args()

    wanted = {s.strip().lower() for s in args.states.split(",") if s.strip()}
    files = sorted(Path(args.dir).rglob("*_bills.csv"))
    # Skip the federal archive (congress_bills already covers the 119th via
    # API) and related-bills edge tables (not bill records).
    files = [
        f for f in files
        if not f.name.startswith("US_") and "related" not in f.name
    ]
    if wanted:
        files = [f for f in files if f.name.split("_")[0].lower() in wanted]
    if not files:
        print("No matching archives found.")
        return 1

    conn = None
    if not args.dry_run:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""CREATE TABLE IF NOT EXISTS state_bills (
                bill_id TEXT PRIMARY KEY, jurisdiction TEXT NOT NULL,
                session TEXT NOT NULL, bill_number TEXT, title TEXT,
                classification TEXT, subjects TEXT, first_action_date TEXT,
                latest_action_date TEXT, latest_action_description TEXT,
                sponsor_count INTEGER, source_url TEXT, fetched_at TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS state_bill_ingest_meta (
                jurisdiction TEXT PRIMARY KEY, session TEXT,
                bills_seen INTEGER, bills_kept INTEGER, fetched_at TEXT)""")

    total_seen = total_kept = 0
    for f in files:
        try:
            m = load_archive(f, conn, dry_run=args.dry_run)
            total_seen += m["seen"]
            total_kept += m["kept"]
            print(f"  {f.parent.name}/{f.name}: seen={m['seen']} kept={m['kept']} "
                  f"sessions={m['sessions']}")
        except Exception as e:
            print(f"  {f}: FAILED {type(e).__name__}: {str(e)[:150]}")
    if conn:
        conn.close()
    print(f"Done: kept={total_kept} of seen={total_seen} "
          f"({'DRY RUN' if args.dry_run else 'saved'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
