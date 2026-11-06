"""Per-ingester ledger and source-freshness checks.

The frequency-level due state lives in ``logs/ingest_ledger.json`` and is
written by ``run_ingestion_startup.ps1``. This file is the per-source
evidence: one entry per ingester, written after every attempt, so a run that
is killed mid-pipeline still leaves an accurate record of what finished.

It answers three questions the frequency-level ledger cannot:

1. Which ingesters already succeeded in this window, so a retry can resume
   instead of redoing the whole frequency.
2. Which ingester timed out or failed, with its own duration and error.
3. How stale each source table actually is. A source can return HTTP 200,
   ingest zero rows, and still be "success" -- freshness is the check that
   notices. Staleness is recorded, not escalated: a structurally lagging
   source (NOAA storm events publish ~3 months late) must not trigger retry
   storms, but it must be visible.

Freshness is a coarse gate: it compares ``max(date_column)`` with a
per-source age limit. Thresholds are publication lags, not wishes.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# module name -> (table, date column, max age in days)
# Limits reflect publication lag, not data quality. A daily market series
# should be current; BLS/permits/NOAA lag their reference month by weeks.
FRESHNESS: Dict[str, tuple[str, str, int]] = {
    # Weekly storage is published Thursday for the prior week-ending Friday.
    # On a Wednesday before release the newest row is 12 days old by
    # construction, so a 10-day limit flags normal publication lag.
    "data_ingest.ingest_eia": ("eia_storage", "timestamp", 14),
    "data_ingest.ingest_lmp": ("grid_lmp", "timestamp", 3),
    "data_ingest.ingest_lmp_multi_iso": ("grid_lmp_multi_iso", "timestamp", 5),
    "data_ingest.ingest_fred": ("fred_macro", "timestamp", 10),
    "data_ingest.ingest_weather": ("weather_observations", "timestamp", 3),
    "data_ingest.ingest_noaa_cpc": ("noaa_degree_days", "date", 10),
    "data_ingest.ingest_gie_storage": ("agsi_storage", "gas_day", 10),
    "data_ingest.ingest_entsog_flows": ("entsog_nominations", "gas_day", 7),
    "data_ingest.ingest_ais_maritime": ("maritime_ais", "timestamp", 3),
    "data_ingest.ingest_stooq": ("stock_prices", "timestamp", 5),
    "data_ingest.ingest_cme_settlements": ("cme_settlements", "trade_date", 10),
    "data_ingest.ingest_cme_futures": ("cme_futures_daily", "date", 10),
    "data_ingest.ingest_drought": ("drought_conditions", "date", 14),
    "data_ingest.ingest_eia_jet_fuel": ("eia_jet_fuel", "date", 10),
    "data_ingest.ingest_bls_ppi": ("bls_ppi", "date", 70),
    "data_ingest.ingest_fred_building_permits": ("census_permits", "date", 90),
    "data_ingest.ingest_congress_bills_expanded": ("congress_bills", "latest_action_date", 30),
    "data_ingest.ingest_storm_events": ("storm_events", "begin_date", 150),
    "data_ingest.ingest_lobbying_disclosures": ("lobbying_filings", "dt_posted", 45),
    "data_ingest.ingest_state_bills": ("state_bills", "latest_action_date", 45),
}


def ledger_path() -> Path:
    override = os.getenv("METIS_INGEST_LEDGER")
    if override:
        return Path(override)
    return PROJECT_ROOT / "logs" / "ingest_ingesters.json"


def load() -> Dict[str, Any]:
    path = ledger_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        # A corrupt ledger must not stop ingestion; it only loses history.
        return {}


def save(data: Dict[str, Any]) -> None:
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def succeeded_within(
    iso_timestamp: Optional[str], frequency: str, now: Optional[datetime] = None
) -> bool:
    """Is ``iso_timestamp`` a success inside the current window for ``frequency``?

    Windows mirror run_ingestion_startup.ps1: daily = same date, weekly = since
    Monday 00:00 (no rolling-7-day drift), monthly = same calendar month.
    """
    if not iso_timestamp:
        return False
    now = now or datetime.now()
    try:
        last = datetime.fromisoformat(str(iso_timestamp))
    except ValueError:
        return False

    last_date = last.date()
    if frequency == "daily":
        return last_date == now.date()
    if frequency == "weekly":
        monday = now.date() - timedelta(days=now.weekday())
        return last_date >= monday
    if frequency == "monthly":
        return (last.year, last.month) == (now.year, now.month)
    return False


def _db_path() -> str:
    url = os.getenv("DB_URL", "")
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///") :]
    return str(PROJECT_ROOT / "data" / "metis.db")


def _parse_datetime(value: Any) -> Optional[datetime]:
    """Parse the mixed date formats stored in the DB (ISO, space-separated, tz-aware)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    candidates = [text.replace("Z", "+00:00"), text[:19], text[:10]]
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    return None


def fresh_for(key: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Measure how old the newest row in this ingester's table is.

    Returns a dict with table, raw max value, age in days, the limit, and a
    ``fresh`` flag. ``fresh`` is None when it cannot be measured (missing
    table, missing column, unparseable value).
    """
    spec = FRESHNESS.get(key)
    if not spec:
        return {"fresh": None, "reason": "no freshness spec"}

    table, column, max_age_days = spec
    result: Dict[str, Any] = {
        "table": table,
        "column": column,
        "max_age_days": max_age_days,
        "source_max_date": None,
        "age_days": None,
        "fresh": None,
    }

    try:
        # Identifiers come from the constant map above, never from input.
        con = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True, timeout=5)
        try:
            row = con.execute(f"SELECT MAX({column}) FROM {table}").fetchone()
        finally:
            con.close()
    except Exception as exc:
        result["reason"] = f"{type(exc).__name__}: {exc}"
        return result

    raw = row[0] if row else None
    result["source_max_date"] = None if raw is None else str(raw)
    parsed = _parse_datetime(raw)
    if parsed is None:
        result["reason"] = "no parseable date" if raw is None else f"unparseable: {raw!r}"
        return result

    now = now or datetime.now()
    age_days = (now - parsed).total_seconds() / 86400.0
    result["age_days"] = round(age_days, 1)
    result["fresh"] = age_days <= max_age_days
    return result


def record_attempt(
    key: str,
    display: str,
    frequency: str,
    status: str,
    duration_ms: float,
    row_count: int = 0,
    exit_code: Optional[int] = None,
    error: str = "",
    fresh: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Write one attempt to the ledger, preserving the last success timestamp."""
    data = load()
    previous = data.get(key) or {}
    now_iso = datetime.now().astimezone().isoformat(timespec="seconds")

    entry: Dict[str, Any] = {
        "display": display,
        "frequency": frequency,
        "status": status,
        "attempted_at": now_iso,
        "last_success_at": previous.get("last_success_at"),
        "duration_ms": int(duration_ms),
        "row_count": int(row_count or 0),
        "exit_code": exit_code,
        "error": error or "",
        "consecutive_failures": previous.get("consecutive_failures", 0),
        "source_max_date": (fresh or {}).get("source_max_date"),
        "source_age_days": (fresh or {}).get("age_days"),
        "fresh": (fresh or {}).get("fresh"),
        "max_age_days": (fresh or {}).get("max_age_days"),
    }

    if status == "success":
        entry["last_success_at"] = now_iso
        entry["consecutive_failures"] = 0
    else:
        entry["consecutive_failures"] = int(entry["consecutive_failures"] or 0) + 1

    data[key] = entry
    save(data)
    return entry
