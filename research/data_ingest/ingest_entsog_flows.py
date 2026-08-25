"""
ENTSOG Transparency Platform - daily EU pipeline-entry Nominations (P1)

Primary outcome series of the pre-registered micro-to-macro test
(notes/pre_registration_micro_to_macro.md):
    russian_share(t) = Russian-corridor entry nominations / ALL EU entry
                       nominations, daily.

API: https://transparency.entsog.eu/api/v1/operationaldatas.json  (open, no key)
Verified contract (Aug 2026, TP_API_UserManual_v3.0):
    indicator=Nomination      (singular, case-sensitive; anything else -> 404)
    periodType=day            directionKey=entry        timeZone=CET
    from/to=YYYY-MM-DD        default limit=100; 60s server execution cap
Response JSON key follows endpoint plurality: 'operationaldatas'.

We store POINT-LEVEL entry rows so corridor definitions can evolve without
re-backfilling; russian_share is derived downstream via keyword match on
point_label (Greifswald/Mallnow/Sudzha/Isaccea/Mediesu/TurkStream...).

USAGE:
  python ingest_entsog_flows.py                 # incremental from meta
  python ingest_entsog_flows.py --from 2019-01-01
"""

import os
import sys
import time
import sqlite3
import logging
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
import requests

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
DB_PATH = DB_URL.replace("sqlite:///", "")

BASE = "https://transparency.entsog.eu/api/v1/operationaldatas.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def get_page(d_from: str, d_to: str, offset: int):
    p = {"indicator": "Nomination", "periodType": "day",
         "directionKey": "entry", "timeZone": "CET",
         "from": d_from, "to": d_to, "limit": 5000, "offset": offset}
    r = requests.get(BASE, params=p, timeout=300)
    if r.status_code == 404:
        return [], None  # window with no data
    r.raise_for_status()
    d = r.json()
    return (d.get("operationaldatas") or []), d.get("meta", {})


PAGE_LIMIT = 5000


def fetch_window(d_from: str, d_to: str):
    """Offset-paginate a window until a PARTIAL page arrives.
    CAUTION: meta.total is 'rows remaining from this offset', NOT the
    window total -- using it as a stop condition truncates every window
    at exactly one page."""
    rows, seen = [], set()
    offset = 0
    while True:
        data, _meta = get_page(d_from, d_to, offset)
        if not data:
            break
        for x in data:
            k = x.get("id")
            if k in seen:
                continue
            seen.add(k)
            rows.append(x)
        offset += len(data)
        if len(data) < PAGE_LIMIT:
            break
        time.sleep(1.2)
    return rows


def ensure_tables(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS entsog_nominations (
            gas_day TEXT NOT NULL,
            point_label TEXT NOT NULL,
            operator_label TEXT,
            point_key TEXT,
            direction TEXT,
            value_kwh_d REAL,
            unit TEXT,
            fetched_at TEXT,
            PRIMARY KEY (gas_day, point_label, operator_label))"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS entsog_ingest_meta (
            key TEXT PRIMARY KEY, value TEXT)"""
    )
    conn.commit()


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def write_rows(conn, rows):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = []
    for x in rows:
        pf = x.get("periodFrom") or ""
        day = pf[:10]
        label = x.get("pointLabel")
        if not day or not label:
            continue  # non-point rows (aggregates/placeholder capacity)
        payload.append((day, x.get("pointLabel"), x.get("operatorLabel"),
                        x.get("pointKey"), x.get("directionKey"),
                        _f(x.get("value")), x.get("unit"), now))
    conn.executemany(
        """INSERT OR REPLACE INTO entsog_nominations VALUES (?,?,?,?,?,?,?,?)""",
        payload)
    return len(payload)


def month_windows(start: datetime, end: datetime):
    cur = start
    while cur <= end:
        nxt = (cur.replace(day=28) + timedelta(days=6)).replace(day=1)
        yield cur.strftime("%Y-%m-%d"), (min(nxt, end + timedelta(days=1))
                                         - timedelta(days=1)).strftime("%Y-%m-%d")
        cur = nxt


def main():
    parser = argparse.ArgumentParser(description="ENTSOG entry-nomination ingestion")
    parser.add_argument("--from", dest="dfrom", type=str, default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = None if args.dry_run else sqlite3.connect(DB_PATH)
    if conn:
        ensure_tables(conn)

    start = args.dfrom or "2019-01-01"
    if conn and not args.dfrom:
        row = conn.execute(
            "SELECT value FROM entsog_ingest_meta WHERE key='last_date'").fetchone()
        if row and row[0] and not args.dfrom:
            start = (datetime.strptime(row[0], "%Y-%m-%d")
                     + timedelta(days=1)).strftime("%Y-%m-%d")

    end = datetime.now().date()
    total = 0
    logger.info(f"Backfill window: {start} .. {end}")
    for wf, wt in month_windows(datetime.strptime(start, "%Y-%m-%d"),
                                datetime.combine(end, datetime.min.time())):
        try:
            rows = fetch_window(wf, wt)
        except Exception as e:
            logger.error(f"{wf}..{wt}: {str(e)[:100]}")
            break
        n = 0 if args.dry_run else write_rows(conn, rows)
        total += len(rows)
        logger.info(f"{wf}..{wt}: {len(rows)} rows ({n} written)")
        time.sleep(1.0)

    if conn and total:
        conn.execute(
            "INSERT OR REPLACE INTO entsog_ingest_meta VALUES ('last_date',?)",
            (end.isoformat(),))
        conn.commit()
        conn.close()
    logger.info(f"Done: {total} rows {'(DRY RUN)' if args.dry_run else ''}")
    return 0 if total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
