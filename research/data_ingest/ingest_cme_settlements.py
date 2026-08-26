"""
CME Direct Settlements Ingestion
Fetches daily settlement curves (all contract months: open/high/low/last/
settle/volume/OI) straight from CME Group's public settlements endpoints,
replacing the Yahoo Finance-derived path for futures EOD data.

How it works:
  - CME's site is behind Akamai TLS fingerprinting: plain HTTP clients get
    403'd and headless browsers get connection-reset. A HEADED Playwright
    Chromium passes cleanly.
  - The page drives the data through CmeWS JSON endpoints keyed by productId:
      /CmeWS/mvc/Settlements/Futures/Settlements/{productId}/FUT?tradeDate=MM/DD/YYYY
  - The endpoint serves only a rolling recent window (~5 trading days), so
    this ingester runs DAILY and captures everything going forward.
    Historical depth comes from the existing cme_futures_daily base
    (overlap-validation strategy - see notes/handoffs).

Product IDs discovered by loading each product's .settlements.html page and
capturing the /Settlements/Futures/TradeDate/{id} request (Aug 2026):
  CL=425 (WTI), BZ=421 (Brent), NG=444 (Henry Hub),
  HO=426 (NY Harbor ULSD), RB=429 (RBOB)

USAGE:
  python ingest_cme_settlements.py                 # all products, last 7 days
  python ingest_cme_settlements.py --days 3        # shorter window
  python ingest_cme_settlements.py --products natural_gas
  python ingest_cme_settlements.py --dry-run       # print rows, no DB write
"""

import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
METIS_MODE = os.getenv("METIS_MODE", "DEV")

DB_PATH = Path(DB_URL.replace("sqlite:///", "")) if not DB_URL.endswith(":memory:") else None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# productId map captured Aug 2026 (see module docstring)
CME_SETTLEMENT_PRODUCTS = {
    "crude_oil_wti": {"product_id": 425, "globex": "CL", "name": "WTI Crude Oil"},
    "crude_oil_brent": {"product_id": 421, "globex": "BZ", "name": "Brent Crude Oil"},
    "natural_gas": {"product_id": 444, "globex": "NG", "name": "Henry Hub Natural Gas"},
    "heating_oil": {"product_id": 426, "globex": "HO", "name": "NY Harbor ULSD"},
    "rbob_gasoline": {"product_id": 429, "globex": "RB", "name": "RBOB Gasoline"},
}

BASE = "https://www.cmegroup.com"
LANDING_PAGE = BASE + "/markets/energy/natural-gas/natural-gas.settlements.html"
PROFILE_DIR = str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "metis_cme_browser")


def _num(s):
    """'-', '', None -> None; '110,328' -> 110328.0; '+.04000' -> 0.04."""
    if s is None:
        return None
    t = str(s).strip().rstrip("A")  # trailing 'A' = actual-sales flag
    if t in ("-", "", "--"):
        return None
    try:
        return float(t.replace(",", ""))
    except ValueError:
        return None


def fetch_window(days_back: int = 7):
    """Yield (product_key, trade_date_iso, row_dict) tuples via headed Chromium."""
    from playwright.sync_api import sync_playwright

    dates = []
    d = datetime.now()
    while len(dates) < days_back + 2 and len(dates) < 12:
        if d.weekday() < 5:  # Mon-Fri; holidays simply return 0 rows
            dates.append(d.strftime("%m/%d/%Y"))
        d -= timedelta(days=1)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            args=["--window-position=-32000,-32000", "--window-size=1200,800"],
            viewport={"width": 1200, "height": 800},
        )
        pg = ctx.new_page()
        logger.info("Opening CME landing page to establish session...")
        pg.goto(LANDING_PAGE, timeout=90000)
        pg.wait_for_timeout(9000)

        for key, cfg in CME_SETTLEMENT_PRODUCTS.items():
            pid = cfg["product_id"]
            ok_dates = 0
            for td in dates:
                url = (
                    f"{BASE}/CmeWS/mvc/Settlements/Futures/Settlements/{pid}/FUT"
                    f"?strategy=DEFAULT&tradeDate={td}&pageSize=500&isProtected"
                )
                try:
                    out = pg.evaluate(
                        """async (u) => {
                            const r = await fetch(u);
                            return {s: r.status, t: await r.text()};
                        }""",
                        url,
                    )
                except Exception as e:
                    logger.warning(f"{key} {td}: fetch failed ({str(e)[:60]})")
                    continue
                if out["s"] != 200:
                    logger.warning(f"{key} {td}: HTTP {out['s']}")
                    continue
                try:
                    payload = json.loads(out["t"])
                except json.JSONDecodeError:
                    logger.warning(f"{key} {td}: non-JSON body")
                    continue
                rows = payload.get("settlements") or []
                trade_iso = datetime.strptime(td, "%m/%d/%Y").strftime("%Y-%m-%d")
                emitted = False
                for row in rows:
                    month = row.get("month")
                    if not month or month.lower() == "total":
                        continue
                    yield key, pid, trade_iso, month, {
                        "open": _num(row.get("open")),
                        "high": _num(row.get("high")),
                        "low": _num(row.get("low")),
                        "last": _num(row.get("last")),
                        "change": _num(row.get("change")),
                        "settle": _num(row.get("settle")),
                        "volume": int(_num(row.get("volume")) or 0),
                        "open_interest": int(_num(row.get("open_interest")) or 0),
                    }
                    emitted = True
                if emitted:
                    ok_dates += 1
            logger.info(f"{cfg['globex']} ({pid}): {ok_dates}/{len(dates)} dates had data")
        ctx.close()


def ensure_table(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cme_settlements (
            product TEXT NOT NULL,
            product_id INTEGER NOT NULL,
            trade_date TEXT NOT NULL,
            contract_month TEXT NOT NULL,
            open REAL, high REAL, low REAL, last REAL,
            change REAL, settle REAL,
            volume INTEGER, open_interest INTEGER,
            fetched_at TEXT,
            PRIMARY KEY (product, trade_date, contract_month)
        )
        """)
    conn.commit()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="CME direct settlements ingestion")
    parser.add_argument("--days", type=int, default=7, help="calendar days to request")
    parser.add_argument("--products", type=str, default="", help="comma-separated subset of keys")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if METIS_MODE != "REAL" and not args.dry_run:
        logger.warning(f"[{METIS_MODE}] mode - running anyway (settlements are public data)")

    if args.products:
        wanted = [k.strip() for k in args.products.split(",")]
        unknown = set(wanted) - set(CME_SETTLEMENT_PRODUCTS)
        if unknown:
            logger.error(f"Unknown products: {unknown}")
            return 1
        for k in list(CME_SETTLEMENT_PRODUCTS):
            if k not in wanted:
                del CME_SETTLEMENT_PRODUCTS[k]

    conn = None
    if not args.dry_run and DB_PATH:
        ensure_table(sqlite3.connect(DB_PATH))
        conn = sqlite3.connect(DB_PATH)

    total = 0
    seen_dates = set()
    batch = []
    for key, pid, trade_iso, month, vals in fetch_window(args.days):
        total += 1
        seen_dates.add((key, trade_iso))
        batch.append((key, pid, trade_iso, month, vals))

    if conn is not None:
        now = datetime.now().isoformat(timespec="seconds")
        for key, pid, trade_iso, month, vals in batch:
            conn.execute(
                """INSERT OR REPLACE INTO cme_settlements
                   (product, product_id, trade_date, contract_month,
                    open, high, low, last, change, settle,
                    volume, open_interest, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    key,
                    pid,
                    trade_iso,
                    month,
                    vals["open"],
                    vals["high"],
                    vals["low"],
                    vals["last"],
                    vals["change"],
                    vals["settle"],
                    vals["volume"],
                    vals["open_interest"],
                    now,
                ),
            )
        conn.commit()
        conn.close()

    logger.info(
        f"Ingestion complete: {total} rows across {len(seen_dates)} "
        f"product-dates ({'DRY RUN' if args.dry_run else 'saved'})"
    )
    return total


if __name__ == "__main__":
    sys.exit(1 if main() == 0 else 0)
