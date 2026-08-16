"""
LDA.gov Lobbying Disclosure Ingester

Built against confirmed, empirically-tested API behavior, not documentation
or memory of the pre-migration Senate-only system:
  - Base URL https://lda.gov/api/v1, Authorization: Token <key>
  - filing_specific_lobbying_issues accepts exactly ONE value per call --
    confirmed via order-flip test that repeated/comma-separated params do
    NOT combine as AND or OR, the API silently keeps only the last given
    value (a common DRF query-param footgun, not documented anywhere we
    could find). So this loops one call per issue code and unions client-side.

Two-table design, since a single filing can carry multiple lobbying
activities, each with its own issue code and lobbyist list -- flattening
into one row per filing would either lose that structure or force choosing
one issue code arbitrarily:
  - lobbying_filings: one row per filing_uuid (client, registrant, income,
    expenses, dates)
  - lobbying_activities: one row per (filing_uuid, activity) with issue
    code, description, and lobbyist names joined as a delimited string
    (SQLite has no native array type; matching the pattern used elsewhere
    in this codebase rather than introducing a third join table for what's
    usually a short list)

Issue codes chosen deliberately, not "everything energy-adjacent":
  ENG (Energy/Nuclear), FUE (Fuel/Gas/Oil) -- direct hits
  UTI (Utilities), ENV (Environment/Superfund), CAW (Clean Air and Water)
  -- real secondary mechanism (gas buyers, permitting)
  MAR (Marine/Maritime), RRR (Railroads) -- tied to specific mechanisms
  already established in this project (LNG shipping, LNG/coal-by-rail),
  not generic energy-sector inclusion
Deliberately excluded: NAT (Natural Resources), TRA (Transportation),
TRD (Trade) -- all real but broad enough to be mostly noise if included.
"""
import os
import sys
from pathlib import Path
from datetime import datetime
import requests
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parents[2]))
from research.common import runtime_config as rc

load_dotenv()
DB_URL = rc.get_db_url()
LDA_API_KEY = os.getenv("LDA_API_KEY")

BASE_URL = "https://lda.gov/api/v1"
HEADERS = {"Authorization": f"Token {LDA_API_KEY}"} if LDA_API_KEY else {}

ISSUE_CODES = ["ENG", "FUE", "UTI", "ENV", "CAW", "MAR", "RRR"]


def fetch_filings_for_code(code: str) -> list:
    """Paginate through all filings for a single issue code."""
    results = []
    url = f"{BASE_URL}/filings/"
    params = {"filing_specific_lobbying_issues": code, "page_size": 250}

    page_num = 1
    while url:
        resp = requests.get(url, headers=HEADERS, params=params if page_num == 1 else None, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("results", []))
        url = data.get("next")
        params = None  # 'next' already contains full query string
        page_num += 1

    print(f"  {code}: {len(results)} filings")
    return results


def normalize_filing(raw: dict) -> tuple:
    """Split one raw filing into (filing_row, [activity_rows])."""
    client = raw.get("client") or {}
    registrant = raw.get("registrant") or {}

    filing_row = {
        "filing_uuid": raw["filing_uuid"],
        "filing_type": raw.get("filing_type"),
        "filing_type_display": raw.get("filing_type_display"),
        "filing_year": raw.get("filing_year"),
        "filing_period": raw.get("filing_period"),
        "income": raw.get("income"),
        "expenses": raw.get("expenses"),
        "dt_posted": raw.get("dt_posted"),
        "registrant_name": registrant.get("name"),
        "registrant_id": registrant.get("id"),
        "client_name": client.get("name"),
        "client_id": client.get("id"),
        "client_state": client.get("state"),
        "filing_document_url": raw.get("filing_document_url"),
    }

    activity_rows = []
    for activity in raw.get("lobbying_activities", []):
        lobbyist_names = ", ".join(
            f"{l.get('lobbyist', {}).get('first_name', '')} {l.get('lobbyist', {}).get('last_name', '')}".strip()
            for l in activity.get("lobbyists", [])
        )
        gov_entities = ", ".join(g.get("name", "") for g in activity.get("government_entities", []))

        activity_rows.append({
            "filing_uuid": raw["filing_uuid"],
            "general_issue_code": activity.get("general_issue_code"),
            "general_issue_code_display": activity.get("general_issue_code_display"),
            "description": activity.get("description"),
            "lobbyist_names": lobbyist_names,
            "government_entities": gov_entities,
        })

    return filing_row, activity_rows


def ensure_tables(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS lobbying_filings (
                filing_uuid TEXT PRIMARY KEY,
                filing_type TEXT,
                filing_type_display TEXT,
                filing_year INTEGER,
                filing_period TEXT,
                income REAL,
                expenses REAL,
                dt_posted TEXT,
                registrant_name TEXT,
                registrant_id INTEGER,
                client_name TEXT,
                client_id INTEGER,
                client_state TEXT,
                filing_document_url TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS lobbying_activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filing_uuid TEXT NOT NULL,
                general_issue_code TEXT,
                general_issue_code_display TEXT,
                description TEXT,
                lobbyist_names TEXT,
                government_entities TEXT
            )
        """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_lobbying_activities_dedup
            ON lobbying_activities(filing_uuid, general_issue_code, lobbyist_names)
        """))


def save_filings(filing_rows: list, activity_rows: list, engine):
    if not filing_rows:
        return 0, 0

    filings_df = pd.DataFrame(filing_rows).drop_duplicates(subset="filing_uuid")
    activities_df = pd.DataFrame(activity_rows).drop_duplicates(
        subset=["filing_uuid", "general_issue_code", "lobbyist_names"]
    )

    with engine.begin() as conn:
        f_cols = list(filings_df.columns)
        f_update = ", ".join(f"{c}=excluded.{c}" for c in f_cols if c != "filing_uuid")
        conn.execute(text(f"""
            INSERT INTO lobbying_filings ({', '.join(f_cols)})
            VALUES ({', '.join(':' + c for c in f_cols)})
            ON CONFLICT(filing_uuid) DO UPDATE SET {f_update}
        """), filings_df.to_dict("records"))

        if not activities_df.empty:
            a_cols = list(activities_df.columns)
            conn.execute(text(f"""
                INSERT OR IGNORE INTO lobbying_activities ({', '.join(a_cols)})
                VALUES ({', '.join(':' + c for c in a_cols)})
            """), activities_df.to_dict("records"))

    return len(filings_df), len(activities_df)


def main():
    rc.log_mode("LDA Lobbying Disclosures")
    if not LDA_API_KEY:
        print("LDA_API_KEY not set -- aborting (anonymous access is rate-limited too "
              "aggressively for a full historical pull)")
        return 0

    engine = create_engine(DB_URL)
    ensure_tables(engine)

    all_raw = {}  # keyed by filing_uuid to dedupe across issue-code queries
    for code in ISSUE_CODES:
        for raw in fetch_filings_for_code(code):
            all_raw[raw["filing_uuid"]] = raw

    print(f"\n{len(all_raw)} unique filings across {len(ISSUE_CODES)} issue codes "
          f"(deduped -- a filing touching multiple chosen codes was only fetched once)")

    filing_rows, activity_rows = [], []
    for raw in all_raw.values():
        f_row, a_rows = normalize_filing(raw)
        filing_rows.append(f_row)
        activity_rows.extend(a_rows)

    n_filings, n_activities = save_filings(filing_rows, activity_rows, engine)
    print(f"Saved {n_filings} filings, {n_activities} activity records")
    return n_filings


if __name__ == "__main__":
    main()
