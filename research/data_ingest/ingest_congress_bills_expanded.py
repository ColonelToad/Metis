"""
Rebuilt Congress.gov bill ingester -- fixes three confirmed problems from the
data audit:

  1. Single Congress hardcoded -- the old default was congress=119 with no
     loop, so the table only ever had 119th Congress data despite the
     congress.gov API going back to the 1970s and our lobbying data starting
     in 2001 (Congress 107). This version loops 107-119 by default, matching
     the lobbying data's temporal depth.

  2. limit=200 with no pagination -- the list endpoint returns max 250 per
     page; the old version fetched one page and stopped. This version follows
     pagination.next until exhausted, getting complete coverage per Congress.

  3. Keyword classification on titles instead of CRS Policy Area -- the real
     authoritative classification lives on the detail endpoint
     (/v3/bill/{congress}/{type}/{number}) in policyArea.name. Fetching the
     detail endpoint for every bill is expensive (~10,000+ bills per Congress
     * 120ms per call = hours). Strategy: first-pass filter on keyword match
     OR known energy-adjacent bill types, then fetch detail only for those.
     This gives authoritative classification where it matters (energy-adjacent
     bills) without paying the cost for every appropriations or naming bill.

Incremental by default (Oct-2026): closed sessions are immutable history --
each is coverage-gated (API count vs DB count) and skipped when complete,
so a quiet month costs ~1 request per old session. The two most recent
sessions always re-fetch (actions advance there). --full forces a complete
rescan (one-shot depth repair). Poison pages (truncated chunked responses)
retry with halved limits; a session that still fails is skipped with a
warning instead of killing the run (upserts so far are kept).

Note on congress.gov API rate limits: 5,000 requests/hour with an API key.
This script sleeps 0.1s between list pages and 0.2s between detail calls.
A --full 107-119 backfill takes approximately 20-40 minutes depending on
bill volume. Incremental monthly runs take ~2 minutes when idle.

Run from C:\\Users\\legot\\Metis:
    python research/data_ingest/ingest_congress_bills_expanded.py
    python research/data_ingest/ingest_congress_bills_expanded.py --congress 119  # single session
    python research/data_ingest/ingest_congress_bills_expanded.py --start-congress 107 --end-congress 119  # range
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import pandas as pd
import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.append(str(Path(__file__).resolve().parents[2]))
from research.common import runtime_config as rc

load_dotenv()
DB_URL = rc.get_db_url()
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY")
BASE_URL = "https://api.congress.gov/v3"


def _current_congress() -> int:
    """Congress number for today's date (119th = 2025-2026)."""
    return (datetime.now(timezone.utc).year + 1) // 2 - 894


CURRENT_CONGRESS = _current_congress()

# First-pass filter: bill types that can plausibly touch energy infrastructure.
# Keeps the detail-endpoint call budget manageable -- we only fetch CRS Policy
# Area for bills that pass this gate, not for every renaming or appropriations bill.
ENERGY_KEYWORDS = [
    "natural gas",
    "lng",
    "pipeline",
    "energy",
    "infrastructure",
    "methane",
    "gas",
    "oil",
    "climate",
    "utility",
    "transmission",
    "grid",
    "nuclear",
    "renewable",
    "carbon",
    "emission",
    "fossil",
    "refinery",
    "electricity",
    "power",
    "storage",
    "export terminal",
    "liquefied",
]

# The CRS Policy Area values that constitute "energy related" -- these are the
# real authoritative classifications from the detail endpoint.
ENERGY_POLICY_AREAS = {
    "Energy",
    "Environmental Protection",
    "Science, Technology, Communications",
    "Transportation and Public Works",
    "Finance and Financial Sector",
    "Public Lands and Natural Resources",
    "Commerce",
}


def is_energy_keyword_match(title: str, summary: str = "") -> tuple:
    blob = f"{title} {summary}".lower()
    matched = [kw for kw in ENERGY_KEYWORDS if kw in blob]
    return bool(matched), ",".join(matched)


def get_headers() -> dict:
    return {"X-API-Key": CONGRESS_API_KEY} if CONGRESS_API_KEY else {}


def fetch_bill_list_page(
    url: str, params: dict, retries: int = 3, label: str = ""
) -> tuple:
    """Fetch list page with a retry loop and extended timeout.

    ChunkedEncodingError (truncated chunked response, e.g. the Oct-2026
    Congress-109 poison page) is retried with a halved limit -- smaller
    payloads route around server-side truncation. Returns (data,
    effective_limit) so the caller keeps the shrunk limit for subsequent
    pages. Raises only after all retries fail.
    """
    params = dict(params)
    for attempt in range(retries):
        try:
            # Increased timeout to 60 seconds
            resp = requests.get(url, headers=get_headers(), params=params, timeout=60)
            resp.raise_for_status()
            return resp.json(), int(params.get("limit", 250) or 250)
        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        ) as e:
            kind = type(e).__name__
            print(
                f"    [!] {kind} on list fetch {label} "
                f"(attempt {attempt + 1}/{retries}, limit={params.get('limit')})."
            )
            if isinstance(e, requests.exceptions.ChunkedEncodingError):
                old = int(params.get("limit", 250) or 250)
                if old > 25:
                    params["limit"] = max(25, old // 2)
                    print(f"    [!] Shrinking page limit {old} -> {params['limit']}.")
            if attempt < retries - 1:
                time.sleep(5)  # Wait 5 seconds before trying again
            else:
                raise  # Fail completely if out of retries


def _with_limit(url: str, limit: int) -> str:
    """Rewrite the limit query param of a (possibly cursor) page URL."""
    parts = urlparse(url)
    q = dict(parse_qsl(parts.query))
    q["limit"] = str(limit)
    return urlunparse(parts._replace(query=urlencode(q)))


def _bill_key(bill: dict) -> tuple:
    return (
        str(bill.get("type", "") or ""),
        str(bill.get("number", "") or ""),
    )


def fetch_all_bills_for_congress(congress: int, limit: int = 250) -> list:
    """Paginate through all bills for a single Congress session.

    Poison-page handling (Oct-2026 Congress-109): a page that keeps failing
    with truncated chunked responses is retried with a halved limit (down to
    25). Because a smaller limit re-fetches an overlapping window, rows are
    deduped by (type, number) so detail-call budgeting downstream is unaffected.
    Raises the last error only if even limit=25 fails -- the caller
    (per-session try/except in main) then skips the session with a warning
    instead of killing the whole run.
    """
    url = f"{BASE_URL}/bill/{congress}"
    params = {
        "format": "json",
        "limit": limit,
    }
    if CONGRESS_API_KEY:
        params["api_key"] = CONGRESS_API_KEY

    all_bills = []
    seen = set()
    page = 1
    while url:
        try:
            data, limit = fetch_bill_list_page(
                _with_limit(url, limit) if page > 1 else url,
                params if page == 1 else {},
                label=f"congress={congress} page={page}",
            )
        except requests.HTTPError as e:
            print(f"  [Congress {congress}] Page {page} fetch error: {e}")
            break

        bills = data.get("bills", [])
        if not bills:
            break

        fresh = [b for b in bills if _bill_key(b) not in seen]
        seen.update(_bill_key(b) for b in bills)
        all_bills.extend(fresh)

        pagination = data.get("pagination", {})
        total = pagination.get("count")
        next_url = pagination.get("next")
        url = next_url if next_url else None
        params = {}  # next URL already contains all params

        page += 1
        if total:
            print(f"  [Congress {congress}] page {page - 1}: {len(all_bills):,}/{total:,} bills")
        time.sleep(0.1)

    return all_bills


def fetch_policy_area(
    congress: int, bill_type: str, bill_number: str, retries: int = 3
) -> Optional[str]:
    """
    Fetch the CRS-assigned Policy Area from the bill detail endpoint.
    Includes a retry loop to prevent single-call timeouts from crashing the script.
    """
    url = f"{BASE_URL}/bill/{congress}/{bill_type.lower()}/{bill_number}"
    params = {"format": "json"}
    if CONGRESS_API_KEY:
        params["api_key"] = CONGRESS_API_KEY

    for attempt in range(retries):
        try:
            # Increased timeout to 60 seconds
            resp = requests.get(url, headers=get_headers(), params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            bill = data.get("bill", {})
            policy_area = bill.get("policyArea", {})
            return policy_area.get("name") if policy_area else None
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt < retries - 1:
                time.sleep(2)
            else:
                return None
        except Exception:
            return None


def db_session_count(engine, congress: int) -> int:
    """Rows already stored for one Congress session (coverage gate)."""
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM congress_bills WHERE congress=:c"), {"c": congress}
        ).fetchone()[0]


def api_session_total(congress: int) -> Optional[int]:
    """Bill total for one session from page 1 (cheap coverage probe)."""
    url = f"{BASE_URL}/bill/{congress}"
    params = {"format": "json", "limit": 10}
    if CONGRESS_API_KEY:
        params["api_key"] = CONGRESS_API_KEY
    try:
        data, _ = fetch_bill_list_page(url, params, label=f"congress={congress} probe")
    except Exception as e:
        print(f"  [Congress {congress}] coverage probe failed: {e}")
        return None
    return (data.get("pagination") or {}).get("count")


def db_classified_keys(engine, congress: int) -> set:
    """(type, number) already carrying a CRS policy_area -- detail gap check."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT bill_type, bill_number FROM congress_bills "
                "WHERE congress=:c AND policy_area IS NOT NULL"
            ),
            {"c": congress},
        ).fetchall()
    return {(str(t or ""), str(n or "")) for t, n in rows}


def process_congress(congress: int, engine, full: bool = False) -> int:
    """Fetch, classify, and upsert all bills for one Congress. Returns row count.

    Incremental rule: closed sessions are immutable history -- if the DB
    already holds every bill the API reports (coverage probe), the session is
    skipped outright, so a quiet month costs ~1 request per old session. The
    two most recent sessions are always fully re-fetched (actions advance
    there), unless --full forces a complete rescan of everything.
    """
    if not full and congress < CURRENT_CONGRESS - 1:
        api_total = api_session_total(congress)
        db_total = db_session_count(engine, congress)
        if api_total is not None and db_total >= api_total and db_total > 0:
            print(
                f"\n[Congress {congress}] Skipping (DB {db_total:,} >= API {api_total:,})."
            )
            return 0
        print(
            f"\n[Congress {congress}] Coverage gap (DB {db_total:,} vs API {api_total}) -- fetching."
            if api_total is not None
            else f"\n[Congress {congress}] Probe failed -- fetching to be safe."
        )
    else:
        print(f"\n[Congress {congress}] Active session -- full fetch...")

    print(f"[Congress {congress}] Fetching bill list...")
    raw_bills = fetch_all_bills_for_congress(congress)
    print(f"[Congress {congress}] {len(raw_bills)} bills fetched")

    if not raw_bills:
        return 0

    # Detail-call gap check: skip CRS fetch for bills already classified.
    classified = db_classified_keys(engine, congress)
    if classified:
        print(f"[Congress {congress}] {len(classified):,} bills already classified -- skipping their detail calls.")

    records = []
    detail_calls = 0
    skipped_detail = 0

    for bill in raw_bills:
        title = bill.get("title", "") or ""
        latest_action = bill.get("latestAction", {}) or {}
        bill_type = bill.get("type", "") or ""
        bill_number = str(bill.get("number", "") or "")

        keyword_hit, matched_keywords = is_energy_keyword_match(title)

        # Fetch CRS Policy Area only for keyword-matched bills -- keeps
        # API call budget manageable while giving authoritative classification
        # where it actually matters.
        policy_area = None
        if keyword_hit and CONGRESS_API_KEY:
            if (bill_type, bill_number) in classified:
                skipped_detail += 1
            else:
                policy_area = fetch_policy_area(congress, bill_type, bill_number)
                detail_calls += 1
                time.sleep(0.2)

        # Final energy classification: CRS Policy Area is authoritative when
        # Fallback date if actionDate is missing in legacy JSON
        # Fallback date if actionDate is missing in legacy JSON
        action_date = latest_action.get("actionDate")

        # 1. First fallback: the date the bill was introduced
        if not action_date and bill.get("introducedDate"):
            action_date = str(bill.get("introducedDate"))[:10]

        # 2. Final fallback: the IT system update date
        if not action_date and bill.get("updateDate"):
            action_date = str(bill.get("updateDate"))[:10]

        # Combine title match and policy area so policy area broadens rather than overrides
        if policy_area is not None:
            is_energy = keyword_hit or (policy_area in ENERGY_POLICY_AREAS)
        else:
            is_energy = keyword_hit

        records.append(
            {
                "congress": congress,
                "bill_type": bill_type,
                "bill_number": bill_number,
                "title": title,
                "origin_chamber": bill.get("originChamber", ""),
                "latest_action_date": action_date,
                "latest_action_text": latest_action.get("text", ""),
                "update_date": bill.get("updateDate"),
                "url": bill.get("url", ""),
                "policy_area": policy_area,
                "is_energy_related": int(is_energy),
                "matched_keywords": matched_keywords,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    df = pd.DataFrame(records)
    energy_count = df["is_energy_related"].sum() if not df.empty else 0
    print(
        f"[Congress {congress}] {len(df)} bills, {energy_count} energy-related, "
        f"{detail_calls} detail calls ({skipped_detail} skipped, already classified)"
    )

    upsert_bills(df, engine)
    return len(df)


def ensure_table(engine):
    with engine.begin() as conn:
        conn.execute(text("""
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
                policy_area TEXT,
                is_energy_related INTEGER,
                matched_keywords TEXT,
                timestamp TIMESTAMP,
                UNIQUE(congress, bill_type, bill_number)
            )
        """))
        # Add policy_area column if this is upgrading an existing table
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(congress_bills)")).fetchall()}
        if "policy_area" not in cols:
            conn.execute(text("ALTER TABLE congress_bills ADD COLUMN policy_area TEXT"))
            print("  Added policy_area column to existing congress_bills table")


def upsert_bills(df: pd.DataFrame, engine):
    if df.empty:
        return
    cols = list(df.columns)
    placeholders = ", ".join(f":{c}" for c in cols)
    update_clause = ", ".join(
        f"{c}=excluded.{c}" for c in cols if c not in ("congress", "bill_type", "bill_number")
    )
    stmt = text(f"""
        INSERT INTO congress_bills ({', '.join(cols)})
        VALUES ({placeholders})
        ON CONFLICT(congress, bill_type, bill_number) DO UPDATE SET {update_clause}
    """)
    with engine.begin() as conn:
        conn.execute(stmt, df.to_dict("records"))


def main(
    start_congress: int = 107,
    end_congress: int = None,
    single: int = None,
    full: bool = False,
):
    rc.log_mode("Congress Bills (Rebuilt)")
    if not CONGRESS_API_KEY:
        print("CONGRESS_API_KEY not set -- aborting")
        return 0

    if end_congress is None:
        end_congress = CURRENT_CONGRESS

    engine = create_engine(DB_URL)
    ensure_table(engine)

    if single is not None:
        congresses = [single]
        full = True  # explicit single-session request always fetches
    else:
        congresses = list(range(start_congress, end_congress + 1))

    print(
        f"Processing Congress sessions: {congresses[0]} to {congresses[-1]} "
        f"({'FULL rescan' if full else 'incremental: active sessions + coverage gaps only'})"
    )
    total = 0
    failed = []
    for congress in congresses:
        # One poisoned session (e.g. Oct-2026 Congress-109 truncated pages)
        # must not discard the other sessions' work -- isolate and continue.
        try:
            total += process_congress(congress, engine, full=full)
        except Exception as e:
            print(f"[Congress {congress}] FAILED ({type(e).__name__}: {e}) -- continuing.")
            failed.append(congress)

    print(f"\nDone. Total bills upserted: {total:,}")
    if failed:
        print(f"Sessions skipped by failure: {failed} (retry next run; upserts so far kept)")

    with engine.connect() as conn:
        for congress in [107, 113, end_congress]:
            row = conn.execute(
                text(
                    "SELECT COUNT(*), SUM(is_energy_related) FROM congress_bills WHERE congress=:c"
                ),
                {"c": congress},
            ).fetchone()
            print(f"  Congress {congress}: {row[0]:,} bills, {row[1] or 0} energy-related")

    # A run that upserted nothing AND skipped sessions is a failure for the
    # scheduler (non-zero exit); partial progress still returns success.
    if total == 0 and failed:
        return -1
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--congress",
        type=int,
        default=None,
        help="Single Congress session to fetch (overrides --start/--end)",
    )
    parser.add_argument(
        "--start-congress",
        type=int,
        default=107,
        help="First Congress to fetch (default: 107, matching lobbying data depth)",
    )
    parser.add_argument(
        "--end-congress",
        type=int,
        default=None,
        help="Last Congress to fetch (default: current Congress)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Force complete rescan of every session (one-shot depth repair)",
    )
    args = parser.parse_args()
    result = main(
        start_congress=args.start_congress,
        end_congress=args.end_congress,
        single=args.congress,
        full=args.full,
    )
    # Total failure (nothing upserted, sessions skipped) exits non-zero;
    # partial progress is success -- the frequency summary, not the exit
    # code, is what the scheduler scans for per-ingester failures.
    raise SystemExit(1 if result == -1 else 0)
