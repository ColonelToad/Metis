"""
Expanded Congress.gov ingestion.
- Fetches recent bills for target Congress sessions.
- Tags energy-related bills via keyword matching.
- Writes to congress_bills (upsert) preserving earlier schema + new flags.

Usage (REAL mode):
    METIS_MODE=REAL python research/data_ingest/ingest_congress_bills_expanded.py --congress 119 --limit 200
"""
import argparse
import os
from datetime import datetime, timezone
from typing import List, Dict, Any

import pandas as pd
import requests
from sqlalchemy import create_engine, text

from research.common import runtime_config as rc

DB_URL = rc.get_db_url("sqlite:///data/metis.db")
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY")

ENERGY_KEYWORDS = [
    "natural gas", "lng", "pipeline", "energy", "infrastructure", "fossil",
    "methane", "gas", "oil", "climate", "utility", "transmission", "grid",
    "export", "import", "terminal", "capacity"
]

API_URL = "https://api.congress.gov/v3/bill/{congress}"


def is_energy_related(title: str, summary: str = "") -> (bool, str):
    text_blob = f"{title} {summary}".lower()
    matched = [kw for kw in ENERGY_KEYWORDS if kw in text_blob]
    return (len(matched) > 0, ",".join(matched))


def fetch_bills(congress: int, limit: int) -> pd.DataFrame:
    if not rc.require_real_mode("Congress.gov API"):
        return pd.DataFrame()
    if not CONGRESS_API_KEY:
        print("[CONGRESS] Missing CONGRESS_API_KEY")
        return pd.DataFrame()

    url = API_URL.format(congress=congress)
    params = {
        "api_key": CONGRESS_API_KEY,
        "format": "json",
        "limit": limit,
        "sort": "updateDate desc",
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("bills", [])
    except Exception as e:
        print(f"[CONGRESS] Fetch failed: {e}")
        return pd.DataFrame()

    records: List[Dict[str, Any]] = []
    for bill in data:
        title = bill.get("title", "")
        summary = bill.get("summary", "") or ""
        latest_action = bill.get("latestAction", {})
        energy_flag, matched = is_energy_related(title, summary)
        records.append({
            "congress": congress,
            "bill_type": bill.get("type", ""),
            "bill_number": bill.get("number", ""),
            "title": title,
            "origin_chamber": bill.get("originChamber", ""),
            "latest_action_date": latest_action.get("actionDate"),
            "latest_action_text": latest_action.get("text", ""),
            "update_date": bill.get("updateDate"),
            "url": bill.get("url", ""),
            "is_energy_related": energy_flag,
            "matched_keywords": matched,
            "timestamp": datetime.now(timezone.utc),
        })
    return pd.DataFrame(records)


def ensure_table(engine) -> None:
    create_sql = """
    CREATE TABLE IF NOT EXISTS congress_bills (
        congress INTEGER,
        bill_type TEXT,
        bill_number TEXT,
        title TEXT,
        origin_chamber TEXT,
        latest_action_date TEXT,
        latest_action_text TEXT,
        update_date TEXT,
        url TEXT,
        is_energy_related INTEGER,
        matched_keywords TEXT,
        timestamp TIMESTAMP,
        UNIQUE(congress, bill_type, bill_number)
    );
    """
    with engine.begin() as conn:
        conn.execute(text(create_sql))
        # Backfill new columns for existing tables
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(congress_bills)"))}
        if "is_energy_related" not in cols:
            conn.execute(text("ALTER TABLE congress_bills ADD COLUMN is_energy_related INTEGER"))
        if "matched_keywords" not in cols:
            conn.execute(text("ALTER TABLE congress_bills ADD COLUMN matched_keywords TEXT"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_congress_bills_unique ON congress_bills(congress, bill_type, bill_number)"))


def upsert_bills(engine, df: pd.DataFrame) -> None:
    if df.empty:
        print("[CONGRESS] No bills to upsert")
        return
    ensure_table(engine)
    insert_sql = """
    INSERT INTO congress_bills (
        congress, bill_type, bill_number, title, origin_chamber,
        latest_action_date, latest_action_text, update_date, url,
        is_energy_related, matched_keywords, timestamp
    ) VALUES (
        :congress, :bill_type, :bill_number, :title, :origin_chamber,
        :latest_action_date, :latest_action_text, :update_date, :url,
        :is_energy_related, :matched_keywords, :timestamp
    )
    ON CONFLICT(congress, bill_type, bill_number) DO UPDATE SET
        title=excluded.title,
        origin_chamber=excluded.origin_chamber,
        latest_action_date=excluded.latest_action_date,
        latest_action_text=excluded.latest_action_text,
        update_date=excluded.update_date,
        url=excluded.url,
        is_energy_related=excluded.is_energy_related,
        matched_keywords=excluded.matched_keywords,
        timestamp=excluded.timestamp;
    """
    records = df.to_dict(orient="records")
    for rec in records:
        ts = rec.get("timestamp")
        if hasattr(ts, "to_pydatetime"):
            rec["timestamp"] = ts.to_pydatetime()
    with engine.begin() as conn:
        conn.execute(text(insert_sql), records)
    print(f"[CONGRESS] Upserted {len(df)} bills into congress_bills")


def main(congress: int = 119, limit: int = 200):
    rc.log_mode("Congress.gov Expanded")
    df = fetch_bills(congress, limit)
    if df.empty:
        return
    engine = create_engine(DB_URL)
    upsert_bills(engine, df)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Expanded Congress.gov ingestion")
    parser.add_argument("--congress", type=int, default=119, help="Congress session (e.g., 119 for 2025-2026)")
    parser.add_argument("--limit", type=int, default=200, help="Max bills to fetch")
    args = parser.parse_args()
    main(args.congress, args.limit)
