"""
State Legislation Ingestion via Plural/Open States (v3 API)

Pulls energy-infrastructure-relevant bills from a curated 10-state shortlist
(chosen by geography x history x law -- see notes handoffs):

    TX  ERCOT / DC-load epicenter        PA  Marcellus gas
    OH  Appalachian coal region          WV  coal-vs-solar paper/reality case
    CA  policy laboratory                NY  first statewide gas ban
    CO  fracking-moratorium politics     ND  Bakken / CO2-pipeline fights
    IA  wind + RVO/pipeline eminent      AZ  solar vs water/land

API: https://v3.openstates.org/bills   (free key: openstates.org/accounts/signup,
header X-API-KEY). Free tier ~= 30 req/min; we sleep between pages.

For each state we resolve its LATEST session, then page through bills filtered
by energy-related subject tags, applying a local keyword filter on titles as a
second net for mislabeled-but-relevant bills. Mirrors the congress_bills
schema philosophy so downstream joins stay uniform.

USAGE:
  python ingest_state_bills.py                 # all shortlist states
  python ingest_state_bills.py --states TX,PA  # subset
  python ingest_state_bills.py --dry-run       # plan without calling API
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
DB_PATH = DB_URL.replace("sqlite:///", "")
API_KEY = os.getenv("OPENSTATES_API_KEY", "").strip()
BASE = "https://v3.openstates.org"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SHORTLIST = [
    "Texas",
    "Pennsylvania",
    "Ohio",
    "West Virginia",
    "California",
    "New York",
    "Colorado",
    "North Dakota",
    "Iowa",
    "Arizona",
]

# OpenStates subject tags that carry energy-infrastructure signal. States
# tag inconsistently, so this is deliberately broad; the title-keyword net
# below catches relevant bills that were tagged differently.
SUBJECTS = [
    "Energy",
    "Utilities",
    "Public Utilities",
    "Natural Resources",
    "Environment",
    "Oil, Gas, & Mining",
    "Mining",
    "Electricity",
]

TITLE_KEYWORDS = re.compile(
    r"\b(energy|utilit(y|ies)|solar|wind|renewable|natural gas|pipeline|"
    r"electric(?:ity|al)?|power plant|grid|transmission|carbon|emission|"
    r"climate|net metering|frack|mining|coal|nuclear|uranium|data center|"
    r"data center|battery storage|hydrogen|lng|liquefied)\b",
    re.IGNORECASE,
)


class OpenStatesClient:
    def __init__(self, api_key: str):
        self.session = requests.Session()
        self.session.headers["X-API-KEY"] = api_key
        # Free tier is 10 req/min (not 30 as older docs claim); 6.5s spacing
        # keeps us safely under with headroom for retries.
        self.min_interval = 6.5
        self._last_call = 0.0

    def get(self, path: str, params: dict = None):
        wait = self.min_interval - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        r = self.session.get(f"{BASE}{path}", params=params or {}, timeout=60)
        self._last_call = time.time()
        if r.status_code == 429:
            logger.warning("Rate limited; sleeping 65s")
            time.sleep(65)
            return self.get(path, params)
        r.raise_for_status()
        return r.json()

    def latest_session(self, jurisdiction: str) -> str:
        """Resolve a state's current session via the LIST endpoint filtered
        client-side. /jurisdictions/{name} 404s, and ?name= matches fuzzily
        (cities named like the state), so exact-match on the state's
        government entry."""
        data = self.get("/jurisdictions", {"name": jurisdiction})
        for x in data.get("results", []):
            if x.get("name") == jurisdiction and x.get("classification") == "government":
                return x["latest_session"]
        raise ValueError(f"State jurisdiction not found for '{jurisdiction}'")

    def iter_energy_bills(self, jurisdiction: str, session: str):
        """Yield raw bill dicts matching ANY listed subject (paginated)."""
        page = 1
        while True:
            data = self.get(
                "/bills",
                {
                    "jurisdiction": jurisdiction,
                    "session": session,
                    "per_page": 40,
                    "page": page,
                    "include": "sponsorships",
                },
            )
            results = data.get("results", [])
            if not results:
                return
            for b in results:
                subjects = set(b.get("subject") or [])
                if subjects & set(SUBJECTS):
                    yield b
            pagination = data.get("pagination") or {}
            total_pages = pagination.get("max_page") or 1
            if page >= total_pages:
                return
            page += 1


def keep_bill(bill: dict) -> bool:
    """Subject match happened upstream; title keywords are the second net."""
    return bool(TITLE_KEYWORDS.search(bill.get("title") or ""))


def ensure_table(conn: sqlite3.Connection):
    conn.execute("""CREATE TABLE IF NOT EXISTS state_bills (
            bill_id TEXT PRIMARY KEY,
            jurisdiction TEXT NOT NULL,
            session TEXT NOT NULL,
            bill_number TEXT,
            title TEXT,
            classification TEXT,
            subjects TEXT,
            first_action_date TEXT,
            latest_action_date TEXT,
            latest_action_description TEXT,
            sponsor_count INTEGER,
            source_url TEXT,
            fetched_at TEXT
        )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS state_bill_ingest_meta (
            jurisdiction TEXT PRIMARY KEY, session TEXT,
            bills_seen INTEGER, bills_kept INTEGER, fetched_at TEXT)""")
    conn.commit()


def flatten(bill: dict) -> tuple:
    actions = sorted(bill.get("actions") or [], key=lambda a: a.get("date") or "")
    last = actions[-1] if actions else {}
    sponsors = [s.get("name") for s in (bill.get("sponsorships") or [])]
    src = bill.get("sources") or [{}]
    source_url = src[0].get("url") if isinstance(src, list) else None
    return (
        bill["id"],
        bill.get("jurisdiction_name") or "",
        bill.get("legislative_session") or "",
        bill.get("identifier"),
        bill.get("title"),
        ",".join(bill.get("classification") or []),
        json.dumps(list(set(bill.get("subject") or []))),
        (actions[0].get("date") if actions else None),
        last.get("date"),
        last.get("description"),
        len(sponsors),
        source_url,
    )


def ingest_state(client: OpenStatesClient, conn, state: str, dry_run=False) -> dict:
    session = client.latest_session(state)
    logger.info(f"{state}: latest session = {session}")
    seen_ids = set()
    rows, meta = [], {"bills_seen": 0, "bills_kept": 0}
    for b in client.iter_energy_bills(state, session):
        meta["bills_seen"] += 1
        if b["id"] in seen_ids or not keep_bill(b):
            continue
        seen_ids.add(b["id"])
        meta["bills_kept"] += 1
        rows.append(flatten(b))
    logger.info(f"{state}: saw {meta['bills_seen']} subject-matched, kept {meta['bills_kept']}")
    if not dry_run and rows:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.executemany(
            """INSERT OR REPLACE INTO state_bills
               (bill_id, jurisdiction, session, bill_number, title,
                classification, subjects, first_action_date,
                latest_action_date, latest_action_description,
                sponsor_count, source_url, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [r + (now,) for r in rows],
        )
        conn.execute(
            """INSERT OR REPLACE INTO state_bill_ingest_meta
               (jurisdiction, session, bills_seen, bills_kept, fetched_at)
               VALUES (?,?,?,?,?)""",
            (state, session, meta["bills_seen"], meta["bills_kept"], now),
        )
        conn.commit()
    return meta


def main():
    parser = argparse.ArgumentParser(description="Open States legislation ingestion")
    parser.add_argument(
        "--states", type=str, default="", help="comma-separated subset (names or abbrs)"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not API_KEY:
        logger.error(
            "OPENSTATES_API_KEY not set. Register free at "
            "https://openstates.org/accounts/signup/ and add it to .env"
        )
        return 1

    states = SHORTLIST
    if args.states:
        wanted = {s.strip().lower() for s in args.states.split(",")}
        states = [s for s in SHORTLIST if s.lower() in wanted or _abbr(s).lower() in wanted]

    conn = None if args.dry_run else sqlite3.connect(DB_PATH)
    if conn:
        ensure_table(conn)

    client = OpenStatesClient(API_KEY)
    totals = {"seen": 0, "kept": 0}
    for state in states:
        try:
            m = ingest_state(client, conn, state, dry_run=args.dry_run)
            totals["seen"] += m["bills_seen"]
            totals["kept"] += m["bills_kept"]
        except Exception as e:
            logger.error(f"{state} failed: {str(e)[:120]}")

    if conn:
        conn.close()
    logger.info(
        f"Done: {totals['kept']} bills kept of {totals['seen']} "
        f"subject-matched ({'DRY RUN' if args.dry_run else 'saved'})"
    )
    return 0 if totals["kept"] > 0 else 1


def _abbr(name: str) -> str:
    return {
        "texas": "tx",
        "pennsylvania": "pa",
        "ohio": "oh",
        "west virginia": "wv",
        "california": "ca",
        "new york": "ny",
        "colorado": "co",
        "north dakota": "nd",
        "iowa": "ia",
        "arizona": "az",
    }.get(name.lower(), name[:2])


if __name__ == "__main__":
    sys.exit(main())
