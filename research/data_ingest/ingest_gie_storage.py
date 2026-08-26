"""
GIE Gas Storage Ingestion - AGSI+ (gas storage) & ALSI (LNG terminals)

Europe's official transparency platforms, operated by Gas Infrastructure
Europe. One API key serves both hosts:

    https://agsi.gie.eu/api/data   x-key header
    https://alsi.gie.eu/api/data

Feeds the micro-to-macro test (notes/pre_registration_micro_to_macro.md):
    P2 = country-level storage fullness trajectories  (AGSI+)
    P3 = LNG terminal send-out                        (ALSI)

Verified against live API (Aug 2026): legacy hosts accept `x-key`; the newer
api.gie.eu gateway demands mTLS/bearer and is NOT used here. Data begins
2019-01-01 for most countries (pre-registration window satisfied). Units:
TWh for volumes, % for `full`.

Country coverage is discovered empirically: we probe a candidate code list
per dataset and persist whichever return data (aggregates 'eu'/'ne' kept too).

USAGE:
  python ingest_gie_storage.py                # incremental (since last date)
  python ingest_gie_storage.py --from 2019-01-01
  python ingest_gie_storage.py --dataset agsi --dry-run
"""

import argparse
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("AGSI_API_KEY", "").strip()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
DB_PATH = DB_URL.replace("sqlite:///", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DATASETS = {
    "agsi": {
        "host": "https://agsi.gie.eu",
        "table": "agsi_storage",
        # EU members + major non-EU storages; misses simply return no rows
        "candidates": [
            "AT",
            "BA",
            "BE",
            "BG",
            "CH",
            "CZ",
            "DE",
            "DK",
            "EE",
            "ES",
            "FI",
            "FR",
            "GR",
            "HR",
            "HU",
            "IE",
            "IT",
            "LT",
            "LU",
            "LV",
            "NL",
            "NO",
            "PL",
            "PT",
            "RO",
            "RS",
            "SE",
            "SI",
            "SK",
            "UA",
            "UK",
        ],
    },
    "alsi": {
        "host": "https://alsi.gie.eu",
        "table": "alsi_storage",
        "candidates": [
            "BE",
            "EL",
            "ES",
            "FI",
            "FR",
            "GR",
            "IT",
            "LT",
            "NL",
            "PL",
            "PT",
            "SE",
            "TR",
            "UK",
        ],
    },
}

DEFAULT_START = "2019-01-01"


def get_json(host: str, path: str, params: dict):
    r = requests.get(f"{host}{path}", headers={"x-key": API_KEY}, params=params, timeout=60)
    if r.status_code == 429:
        logger.warning("Rate limited; sleeping 30s")
        time.sleep(30)
        return get_json(host, path, params)
    r.raise_for_status()
    return r.json()


def fetch_range(host: str, country: str, d_from: str, d_till: str):
    """Page through one country's daily rows between dates."""
    out, page = [], 1
    while True:
        d = get_json(
            host,
            "/api/data",
            {"country": country, "from": d_from, "till": d_till, "page": page, "size": 200},
        )
        rows = d.get("data") or []
        out.extend(rows)
        if page >= (d.get("last_page") or 1) or not rows:
            break
        page += 1
    return out


def ensure_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS agsi_storage (
            country TEXT NOT NULL, gas_day TEXT NOT NULL,
            gas_in_storage_twh REAL, injection_gwh_d REAL, withdrawal_gwh_d REAL,
            net_withdrawal_gwh_d REAL, full_pct REAL, trend REAL,
            working_gas_volume_twh REAL, available_capacity_twh REAL,
            contracted_capacity_twh REAL, consumption_gwh_d REAL,
            status TEXT, updated_at TEXT, fetched_at TEXT,
            PRIMARY KEY (country, gas_day))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS alsi_storage (
            country TEXT NOT NULL, gas_day TEXT NOT NULL,
            inventory_gwh REAL, sendout_gwh_d REAL,
            dtrs_gwh_d REAL, dtmi_gwh REAL,
            status TEXT, updated_at TEXT, fetched_at TEXT,
            PRIMARY KEY (country, gas_day))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS gie_ingest_meta (
            dataset TEXT NOT NULL, country TEXT NOT NULL,
            last_date TEXT, active INTEGER, fetched_at TEXT,
            PRIMARY KEY (dataset, country))""")
    conn.commit()


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def write_agsi(conn, country, rows):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = []
    for r in rows:
        day = r.get("gasDayStart")
        if not day:
            continue
        payload.append(
            (
                country,
                day[:10],
                _f(r.get("gasInStorage")),
                _f(r.get("injection")),
                _f(r.get("withdrawal")),
                _f(r.get("netWithdrawal")),
                _f(r.get("full")),
                _f(r.get("trend")),
                _f(r.get("workingGasVolume")),
                _f(r.get("availableCapacity")),
                _f(r.get("contractedCapacity")),
                _f(r.get("consumption")),
                r.get("status"),
                r.get("updatedAt"),
                now,
            )
        )
    conn.executemany(
        """INSERT OR REPLACE INTO agsi_storage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", payload
    )
    return len(payload)


def _gwh(v):
    """ALSI nests energy values as {lng:..., gwh:...}; take the gwh leg."""
    if isinstance(v, dict):
        return _f(v.get("gwh"))
    return _f(v)


def write_alsi(conn, country, rows):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = []
    for r in rows:
        day = r.get("gasDayStart")
        if not day:
            continue
        payload.append(
            (
                country,
                day[:10],
                _gwh(r.get("inventory")),
                _f(r.get("sendOut")),
                _f(r.get("dtrs")),
                _gwh(r.get("dtmi")),
                r.get("status"),
                r.get("updatedAt"),
                now,
            )
        )
    conn.executemany("""INSERT OR REPLACE INTO alsi_storage VALUES (?,?,?,?,?,?,?,?,?)""", payload)
    return len(payload)


def discover_active(conn, host, dataset, candidates):
    """Probe each candidate once over a tiny window; mark which have data."""
    actives = []
    for c in candidates:
        try:
            rows = fetch_range(host, c, "2024-06-01", "2024-06-03")
        except Exception as e:
            logger.warning(f"{dataset}/{c}: probe failed {str(e)[:60]}")
            continue
        if rows:
            actives.append(c)
        time.sleep(0.8)
    logger.info(f"{dataset}: active countries = {actives}")
    return actives


def main():
    parser = argparse.ArgumentParser(description="GIE AGSI+/ALSI ingestion")
    parser.add_argument("--dataset", choices=["agsi", "alsi"], default="")
    parser.add_argument("--from", dest="dfrom", type=str, default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not API_KEY:
        logger.error("AGSI_API_KEY not set in .env")
        return 1

    datasets = [args.dataset] if args.dataset else list(DATASETS)
    conn = None if args.dry_run else sqlite3.connect(DB_PATH)
    if conn:
        ensure_tables(conn)

    today = datetime.now().strftime("%Y-%m-%d")
    grand_total = 0

    for ds in datasets:
        cfg = DATASETS[ds]
        host, table = cfg["host"], cfg["table"]

        # Which countries are active (cached in meta after first run).
        # Discovery is considered complete only when EVERY candidate has a
        # meta row (active or not) -- otherwise an interrupted first run
        # would silently shrink the universe.
        meta = {}
        if conn:
            meta = {
                r[0]: r[1]
                for r in conn.execute(
                    f"SELECT country, active FROM gie_ingest_meta WHERE dataset=?", (ds,)
                )
            }
        if len(meta) >= len(cfg["candidates"]):
            actives = [c for c, a in meta.items() if a]
        else:
            actives = discover_active(conn, host, ds, cfg["candidates"])
            if conn:
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                for c in cfg["candidates"]:
                    conn.execute(
                        f"INSERT OR REPLACE INTO gie_ingest_meta VALUES " f"(?,?,NULL,?,?)",
                        (ds, c, 1 if c in actives else 0, now),
                    )
                conn.commit()

        for country in actives:
            start = args.dfrom or DEFAULT_START
            if conn:
                last = meta.get(country)
                if last and not args.dfrom:
                    last_date = conn.execute(
                        "SELECT last_date FROM gie_ingest_meta WHERE dataset=? " "AND country=?",
                        (ds, country),
                    ).fetchone()
                    if last_date and last_date[0]:
                        start = (
                            datetime.strptime(last_date[0], "%Y-%m-%d") + timedelta(days=1)
                        ).strftime("%Y-%m-%d")
            if start > today:
                continue

            cursor = datetime.strptime(start, "%Y-%m-%d")
            end = datetime.strptime(today, "%Y-%m-%d")
            n = 0
            while cursor <= end:
                chunk_end = min(cursor + timedelta(days=364), end).strftime("%Y-%m-%d")
                chunk_start = cursor.strftime("%Y-%m-%d")
                try:
                    rows = fetch_range(host, country, chunk_start, chunk_end)
                except Exception as e:
                    logger.error(f"{ds}/{country} {chunk_start}: {str(e)[:80]}")
                    break
                if rows:
                    n += len(rows)
                    if not args.dry_run:
                        if ds == "agsi":
                            write_agsi(conn, country, rows)
                        else:
                            write_alsi(conn, country, rows)
                cursor += timedelta(days=365)
                time.sleep(0.6)

            logger.info(f"{ds}/{country}: {n} rows ({start}..{today})")
            grand_total += n
            if conn and n:
                last_day = today
                conn.execute(
                    f"INSERT OR REPLACE INTO gie_ingest_meta VALUES "
                    f"('{ds}','{country}','{last_day}',1,'{today}')"
                )
                conn.commit()
            time.sleep(0.6)

    if conn:
        conn.close()
    logger.info(f"Done: {grand_total} rows {'(DRY RUN)' if args.dry_run else ''}")
    return 0 if grand_total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
