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

For each state we resolve its OCD jurisdiction id, then pull bills across
server-side full-text terms (Q_TERMS), applying the local title-keyword
filter as the keeper gate. Incremental and update-driven: with a stored
waterline we pass updated_since, so a quiet month costs a handful of
requests; the first run pulls full q-matched history. Mirrors the
congress_bills schema philosophy so downstream joins stay uniform.

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

# Server-side full-text query terms (one paginated pull each, deduped by bill
# id). Replaces the old SUBJECTS tag list, which is doubly dead: the v3
# ?subject= filter matches nothing, and subject vocabularies are now
# state-specific codes (e.g. TX "CONDEMNATION (S0063)"). The TITLE_KEYWORDS
# net below stays as the keeper gate client-side.
Q_TERMS = ["energy", "pipeline", "grid", "solar", "wind", "natural gas"]

class QuotaExhausted(RuntimeError):
    """429 from OpenStates: the account window is blown. Any further calls
    are pure waste and risk the key -- abort the whole run immediately."""


class ApiError(RuntimeError):
    """Any other API failure. Conservative policy (Oct-2026): the API
    tightens without notice, so fail the state fast rather than retrying
    into a changed endpoint."""


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
        # keeps us safely under with headroom for retries. First full-history
        # backfills are paced slower (BACKFILL_INTERVAL) -- Oct-2026: ~1000
        # requests at 6.5s tripped sustained 429s for 7.7h straight.
        self.min_interval = float(os.getenv("OPENSTATES_MIN_INTERVAL", "6.5"))
        self.backfill_interval = float(os.getenv("OPENSTATES_BACKFILL_INTERVAL", "11"))
        self._default_interval = self.min_interval
        self._last_call = 0.0

    def use_backfill_pace(self, on: bool = True):
        """Slow request pacing for full-history loads (reset per state)."""
        self.min_interval = self.backfill_interval if on else self._default_interval

    def get(self, path: str, params: dict = None):
        # Fail-fast policy (Oct-2026): ONE 429 -- or any error -- aborts the
        # call chain at once. No retries, no backoff sleeps. Rationale: bulk
        # CSVs are now the load path (data/cache/state_bills_bulk/); the API
        # only serves tiny updated_since deltas, and grinding against 429s
        # for 7.7h both wastes time and risks the key.
        wait = self.min_interval - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            r = self.session.get(f"{BASE}{path}", params=params or {}, timeout=60)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            raise ApiError(f"{type(e).__name__} on {path}: {e}")
        self._last_call = time.time()
        if r.status_code == 429:
            raise QuotaExhausted(f"429 on {path} -- aborting run to protect quota")
        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            raise ApiError(f"{r.status_code} on {path}: {e}")
        return r.json()

    def resolve_jurisdiction(self, state_name: str) -> str:
        """Resolve a state to its OCD jurisdiction id via the detail endpoint
        (Oct-2026 v3 shape: classification is "state", no latest_session
        anywhere, ?name= unfiltered, per_page capped -- list-and-match is
        dead; the OCD id pattern is the stable handle)."""
        from urllib.parse import quote

        ocd = f"ocd-jurisdiction/country:us/state:{_abbr(state_name)}/government"
        try:
            data = self.get(f"/jurisdictions/{quote(ocd, safe='')}")
        except Exception as e:
            raise ValueError(f"State jurisdiction not found for '{state_name}': {e}")
        if not isinstance(data, dict) or data.get("id") != ocd:
            raise ValueError(f"State jurisdiction not found for '{state_name}'")
        return ocd

    def latest_session(self, jurisdiction: str) -> str:
        """Back-compat wrapper (no longer used for fetching -- kept for probes)."""
        return self.resolve_jurisdiction(jurisdiction)

    def iter_energy_bills(
        self, jurisdiction_id: str, updated_since: str = None, session: str = None
    ):
        """Yield raw bill dicts for one state across Q_TERMS (deduped by id).

        Update-driven incremental: with updated_since set (ISO datetime),
        only bills touched since the last fetch page through -- a quiet month
        costs a handful of requests. First run (updated_since=None) pulls the
        full q-matched history. `session` optionally pins one session id.
        """
        seen = set()
        for term in Q_TERMS:
            # per_page cap is 20 on /bills (anything higher 400s).
            params = {
                "jurisdiction": jurisdiction_id,
                "q": term,
                "per_page": 20,
                "page": 1,
                "include": "sponsorships",
            }
            if updated_since:
                params["updated_since"] = updated_since
            if session:
                params["session"] = session
            page = 1
            term_seen = 0
            while True:
                params["page"] = page
                data = self.get("/bills", params)
                results = data.get("results", [])
                if not results:
                    break
                for b in results:
                    if b.get("id") in seen:
                        continue
                    seen.add(b.get("id"))
                    term_seen += 1
                    yield b
                pagination = data.get("pagination") or {}
                total_pages = pagination.get("max_page") or 1
                if page >= total_pages:
                    break
                page += 1
            logger.info(f"    q={term!r}: {term_seen} new bills")


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


def flatten(bill: dict, state_name: str) -> tuple:
    """Remap current v3 schema (Oct-2026): session is an int-as-string,
    jurisdiction is nested, action dates are top-level, sponsors need
    include=sponsorships, openstates_url replaces sources[0]."""
    jur = bill.get("jurisdiction") or {}
    sponsors = bill.get("sponsorships") or []
    return (
        bill["id"],
        jur.get("name") or state_name,
        str(bill.get("session") or ""),
        bill.get("identifier"),
        bill.get("title"),
        ",".join(bill.get("classification") or []),
        json.dumps(list(set(bill.get("subject") or []))),
        bill.get("first_action_date"),
        bill.get("latest_action_date"),
        bill.get("latest_action_description"),
        len(sponsors),
        bill.get("openstates_url"),
    )


def last_fetch(conn, state: str) -> str:
    """Newest fetched_at for one state (update-driven incremental waterline)."""
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT MAX(fetched_at) FROM state_bill_ingest_meta WHERE jurisdiction=?",
            (state,),
        ).fetchone()
        return row[0] if row else None
    except Exception:
        return None


def ingest_state(client: OpenStatesClient, conn, state: str, dry_run=False) -> dict:
    from datetime import timedelta

    jur_id = client.resolve_jurisdiction(state)
    since = None if dry_run else last_fetch(conn, state)
    if since:
        # fetched_at is second-precision: rewind a day so boundary updates
        # landing in the same second aren't silently missed (dedup by id
        # makes the overlap free).
        since = (datetime.fromisoformat(since) - timedelta(days=1)).isoformat(
            timespec="seconds"
        )
    # Full-history loads run at backfill pace; incrementals at normal pace.
    client.use_backfill_pace(since is None)
    try:
        logger.info(f"{state}: {jur_id} updated_since={since or 'full history'}")
        return _ingest_state_inner(client, conn, state, jur_id, since, dry_run)
    finally:
        client.use_backfill_pace(False)


def _ingest_state_inner(client: OpenStatesClient, conn, state: str, jur_id: str,
                        since: str, dry_run: bool = False) -> dict:
    seen_ids = set()
    rows, meta = [], {"bills_seen": 0, "bills_kept": 0, "sessions": set()}
    for b in client.iter_energy_bills(jur_id, updated_since=since):
        meta["bills_seen"] += 1
        if b["id"] in seen_ids or not keep_bill(b):
            continue
        seen_ids.add(b["id"])
        meta["bills_kept"] += 1
        meta["sessions"].add(str(b.get("session") or ""))
        rows.append(flatten(b, state))
    logger.info(f"{state}: saw {meta['bills_seen']} q-matched, kept {meta['bills_kept']}")
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
            (state, ",".join(sorted(meta["sessions"])), meta["bills_seen"], meta["bills_kept"], now),
        )
        conn.commit()
    elif not dry_run and not rows:
        logger.warning(f"{state}: zero bills kept -- state stays empty this run")
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

    # Quota pre-check: one cheap call before spending anything. A 429 here
    # means the account window is blown -- exit at once, don't grind.
    try:
        client.resolve_jurisdiction(states[0])
    except QuotaExhausted as e:
        logger.error(f"Quota pre-check failed: {e}. Aborting run (retry tomorrow).")
        if conn:
            conn.close()
        return 2
    except Exception as e:
        logger.error(f"Pre-check failed: {str(e)[:120]}. Aborting run.")
        if conn:
            conn.close()
        return 1

    totals = {"seen": 0, "kept": 0}
    for state in states:
        try:
            m = ingest_state(client, conn, state, dry_run=args.dry_run)
            totals["seen"] += m["bills_seen"]
            totals["kept"] += m["bills_kept"]
        except QuotaExhausted as e:
            logger.error(f"{state}: {e}. Aborting remaining states to protect quota.")
            break
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
