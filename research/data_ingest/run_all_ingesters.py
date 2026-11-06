"""
Run data ingesters in sequence with frequency support.
Supports daily, weekly, and monthly scheduled execution.

Frequencies:
  - daily: EIA, LMP, FRED Macro, Weather, Maritime AIS, Stock Prices (run every day)
  - weekly: CME Futures, Drought Monitor, EIA Jet Fuel (run Mondays only)
  - monthly: BLS PPI, FRED Building Permits, Congress Bills, NOAA Storm Events, LDA Lobbying Disclosures, Lobbying Bill Reference Extraction (run once per month)
  - all: run all above regardless of schedule

Environment:
  - METIS_MODE=PROD: Enable all real API calls (LMP ISOs, PJM)
  - METIS_MODE=DEV: Skip live API calls for development/testing
"""

import argparse
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add parent directory (research/) to Python path so we can import from data_ingest/
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import all ingesters using qualified paths
from data_ingest import (
    ingest_ais_maritime,
    ingest_bls_ppi,
    ingest_cme_futures,
    ingest_congress_bills_expanded,
    ingest_drought,
    ingest_eia,
    ingest_eia_jet_fuel,
    ingest_entsog_flows,
    ingest_fred,
    ingest_fred_building_permits,
    ingest_gie_storage,
    ingest_ledger,
    ingest_lmp,
    ingest_lmp_multi_iso,
    ingest_lobbying_disclosures,
    ingest_noaa_cpc,
    ingest_state_bills,
    ingest_stooq,
    ingest_storm_events,
    ingest_weather,
)
from features import extract_lobbying_bill_references

# Import log rotation. ``ops`` is a namespace package under research/, so this
# works whether the entry point is the wrapper (research/ops on sys.path) or
# run_all_ingesters itself (research/ on sys.path).
from ops.log_rotation import rotate_logs

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Environment mode
METIS_MODE = os.getenv("METIS_MODE", "DEV")
logger.info(f"Running in {METIS_MODE} mode")


def is_monday() -> bool:
    """Check if today is Monday."""
    return datetime.now().weekday() == 0


def should_run_weekly(force: bool = False) -> bool:
    """
    Determine if weekly ingesters should run.
    Returns True if:
      - force=True (--force-weekly flag), or
      - Today is Monday, or
      - Running 'all' frequency
    """
    if force:
        logger.info("Weekly ingesters forced to run")
        return True
    if is_monday():
        logger.info("Today is Monday - running weekly ingesters")
        return True
    logger.debug("Skipping weekly ingesters (not Monday and no --force flag)")
    return False


DAILY_INGESTERS = [
    ("EIA Natural Gas", ingest_eia),
    ("Grid LMP (CAISO)", ingest_lmp),
    ("Grid LMP (Multi-ISO)", ingest_lmp_multi_iso),
    ("FRED Macro", ingest_fred),
    ("Weather", ingest_weather),
    ("NOAA Degree Days (CPC)", ingest_noaa_cpc),
    ("GIE Gas Storage (AGSI+/ALSI)", ingest_gie_storage),
    ("ENTSOG Entry Nominations", ingest_entsog_flows),
    ("Maritime AIS", ingest_ais_maritime),
    ("Stock Prices", ingest_stooq),
    # CME settlements is parked: CME blocks this IP for scraping (HTTP 403,
    # "blocked due to suspected web scraping activity") and the Playwright path
    # now fails with ERR_HTTP2_PROTOCOL_ERROR. The module is kept for when a
    # licensed/alternate route is chosen; see docs/data_issues.md.
]

WEEKLY_INGESTERS = [
    ("CME Futures", ingest_cme_futures),
    ("Drought Monitor", ingest_drought),
    ("EIA Jet Fuel", ingest_eia_jet_fuel),
]

MONTHLY_INGESTERS = [
    ("BLS Producer Price Index", ingest_bls_ppi),
    ("FRED Building Permits", ingest_fred_building_permits),
    ("Congress Bills", ingest_congress_bills_expanded),
    ("NOAA Storm Events", ingest_storm_events),
    ("LDA Lobbying Disclosures", ingest_lobbying_disclosures),
    # 10-state shortlist energy bills via Plural/Open States (free key;
    # see ingest_state_bills.py header for state rationale)
    ("State Bills (Open States)", ingest_state_bills),
    # Must run after LDA Lobbying Disclosures immediately above -- reads the
    # lobbying_activities/lobbying_filings tables that ingester just wrote.
    # Ordering in this list is the only thing enforcing that dependency
    # (run_all() executes sequentially), so don't reorder these two.
    ("Lobbying Bill Reference Extraction", extract_lobbying_bill_references),
]


# ── Per-ingester execution ────────────────────────────────────────────────────
# Each ingester runs in its own process, so one hung source cannot consume the
# whole frequency budget or take the run down with it. Caps are per attempt and
# sit well above measured healthy runs; they only fire when a source stops
# making progress. Congress legitimately needs ~38 min (118/119 sessions).
INGESTER_TIMEOUTS = {
    "data_ingest.ingest_ais_maritime": 900,  # measured 612s
    "data_ingest.ingest_congress_bills_expanded": 2700,  # measured ~2275s
    "data_ingest.ingest_lmp_multi_iso": 900,  # multi-ISO catch-up; ISO-NE ~15s/day
    "data_ingest.ingest_state_bills": 1200,  # measured ~660s
    "data_ingest.ingest_storm_events": 600,
    "data_ingest.ingest_lobbying_disclosures": 600,
}

DEFAULT_TIMEOUTS = {"daily": 300, "weekly": 600, "monthly": 900, "all": 900}
FALLBACK_TIMEOUT = 900

CHILD_SCRIPT = Path(__file__).resolve().parent / "run_one_ingester.py"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def list_ingesters():
    """Return every known ingester as (display name, module) pairs."""
    return DAILY_INGESTERS + WEEKLY_INGESTERS + MONTHLY_INGESTERS


def ingester_frequency(module) -> str:
    """Home frequency of an ingester (the Monday daily run also carries weekly ones)."""
    name = module.__name__
    if any(name == m.__name__ for _, m in DAILY_INGESTERS):
        return "daily"
    if any(name == m.__name__ for _, m in WEEKLY_INGESTERS):
        return "weekly"
    return "monthly"


def ingester_timeout(module, frequency: str, override: Optional[int] = None) -> int:
    if override:
        return override
    return INGESTER_TIMEOUTS.get(module.__name__, DEFAULT_TIMEOUTS.get(frequency, FALLBACK_TIMEOUT))


def _child_env() -> Dict[str, str]:
    env = os.environ.copy()
    paths = [str(PROJECT_ROOT), str(PROJECT_ROOT / "research")]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["PYTHONIOENCODING"] = "utf-8"
    env["METIS_INGEST_CHILD"] = "1"
    return env


def run_ingester_child(module_name: str, timeout: int) -> Dict[str, object]:
    """Run one ingester in a child process, streaming and timing its output.

    Output is streamed as it arrives and drained after a kill, so a timeout
    still leaves the partial log behind. Returns status, exit_code, rows and
    duration_ms.
    """
    started = time.time()
    process = subprocess.Popen(
        [sys.executable, "-u", str(CHILD_SCRIPT), module_name],
        cwd=str(PROJECT_ROOT),
        env=_child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    stream: "queue.Queue[Optional[str]]" = queue.Queue()

    def pump() -> None:
        try:
            for line in process.stdout:
                stream.put(line)
        finally:
            stream.put(None)

    threading.Thread(target=pump, daemon=True).start()

    collected: List[str] = []
    timed_out = False
    deadline = started + timeout
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            timed_out = True
            break
        try:
            line = stream.get(timeout=min(remaining, 0.5))
        except queue.Empty:
            continue
        if line is None:
            break
        collected.append(line)
        print(line, end="", flush=True)

    if timed_out:
        process.kill()

    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()

    # Drain anything the pump buffered before the process exited or died.
    while True:
        try:
            line = stream.get(timeout=0.2)
        except queue.Empty:
            break
        if line is None:
            break
        collected.append(line)
        print(line, end="", flush=True)

    duration_ms = (time.time() - started) * 1000.0
    rows = 0
    for line in collected:
        if line.startswith("INGEST_ROWS="):
            try:
                rows = int(line.strip().split("=", 1)[1])
            except ValueError:
                rows = 0

    if timed_out:
        return {"status": "timeout", "exit_code": None, "rows": rows, "duration_ms": duration_ms}
    if process.returncode == 0:
        return {"status": "success", "exit_code": 0, "rows": rows, "duration_ms": duration_ms}
    return {
        "status": "failed",
        "exit_code": process.returncode,
        "rows": rows,
        "duration_ms": duration_ms,
    }


def get_ingesters_for_frequency(frequency: str) -> list:
    """
    Return list of (name, module) tuples based on frequency.

    For 'daily': Always include DAILY_INGESTERS; include WEEKLY_INGESTERS only on Monday.
    For 'weekly': Always include WEEKLY_INGESTERS (implies Monday schedule or --force).
    For 'all': Include everything.
    """
    if frequency == "daily":
        # Always run daily ingesters
        ingesters = DAILY_INGESTERS.copy()
        # On Monday, also include weekly
        if is_monday():
            ingesters.extend(WEEKLY_INGESTERS)
            logger.info("Monday detected - including weekly ingesters in daily run")
        return ingesters
    elif frequency == "weekly":
        return WEEKLY_INGESTERS
    elif frequency == "monthly":
        return MONTHLY_INGESTERS
    elif frequency == "all":
        return DAILY_INGESTERS + WEEKLY_INGESTERS + MONTHLY_INGESTERS
    else:
        raise ValueError(f"Unknown frequency: {frequency}")


def get_frequency_description(frequency: str) -> str:
    """Return human-readable description of frequency."""
    is_mon = is_monday()
    descriptions = {
        "daily": f"Daily run (EIA, LMP, Multi-ISO LMP, FRED, Weather, AIS, Stock Prices)"
        + (f" + Weekly CME Futures (Monday)" if is_mon else ""),
        "weekly": "Weekly run (CME Futures, Drought Monitor, EIA Jet Fuel) - Runs Mondays",
        "monthly": "Monthly run (BLS PPI, FRED Building Permits, Congress Bills, NOAA Storm Events, LDA Lobbying Disclosures, Lobbying Bill Reference Extraction)",
        "all": "All ingesters (daily + weekly + monthly)",
    }
    return descriptions.get(frequency, frequency)


def run_all(
    frequency: str = "all",
    collector=None,
    force_weekly: bool = False,
    resume: bool = True,
    force: bool = False,
    timeout_override: Optional[int] = None,
    only: Optional[str] = None,
) -> Tuple[bool, List[Dict]]:
    """
    Run ingesters filtered by frequency.

    Args:
        frequency: 'daily', 'weekly', 'monthly', or 'all'
        collector: Optional MetricsCollector instance to log results
        force_weekly: If True, run weekly ingesters even if not Monday
        resume: Skip ingesters the ledger marks successful in this window
        force: Ignore the ledger and rerun every ingester
        timeout_override: Per-ingester timeout in seconds (testing/manual runs)
        only: Run a single ingester by module name (manual recovery)

    Returns:
        (overall_success: bool, results: list of dicts with ingester status)
    """
    # Handle weekly scheduling for 'daily' frequency
    if frequency == "daily" and not is_monday():
        logger.info("Daily run scheduled (not Monday, skipping weekly ingesters)")

    ingesters = get_ingesters_for_frequency(frequency)
    if only:
        ingesters = [(name, module) for name, module in ingesters if module.__name__ == only]
        if not ingesters:
            print(f"Unknown ingester for frequency {frequency}: {only}")
            return False, []

    print(f"\n{'='*70}")
    print(f"Starting {get_frequency_description(frequency)}: {datetime.now()}")
    print(f"Mode: {METIS_MODE} | Ingesters: {len(ingesters)} | resume={resume and not force}")
    print(f"{'='*70}\n")

    ledger = ingest_ledger.load()
    results: List[Dict] = []
    all_ok = True

    for name, module in ingesters:
        key = module.__name__
        home_frequency = ingester_frequency(module)

        # Resume: a retry after a partial failure should only redo the
        # ingesters that did not succeed, not the whole frequency.
        if resume and not force:
            prior = ledger.get(key) or {}
            if prior.get("status") == "success" and ingest_ledger.succeeded_within(
                prior.get("last_success_at"), home_frequency
            ):
                print(f"SKIP {name}: succeeded {prior.get('last_success_at')} (ledger)")
                results.append(
                    {
                        "name": name,
                        "status": "skipped",
                        "duration_ms": 0,
                        "row_count": 0,
                        "error": None,
                    }
                )
                continue

        timeout = ingester_timeout(module, home_frequency, timeout_override)
        logger.info(f"Running {name} ingester (timeout {timeout}s)")
        print(f"\n>>> {name} ingester")

        outcome = run_ingester_child(key, timeout)
        status = str(outcome["status"])
        error_msg = None
        if status == "timeout":
            error_msg = f"timeout after {timeout}s"
        elif status == "failed":
            error_msg = f"exit code {outcome['exit_code']}"

        # Measure freshness after every attempt: the table's age is a fact
        # about the data, independent of whether this attempt succeeded.
        fresh = ingest_ledger.fresh_for(key)
        ingest_ledger.record_attempt(
            key=key,
            display=name,
            frequency=home_frequency,
            status=status,
            duration_ms=outcome["duration_ms"],
            row_count=int(outcome["rows"]),
            exit_code=outcome["exit_code"],
            error=error_msg or "",
            fresh=fresh,
        )

        if status == "success":
            logger.info(f"✓ {name}: {outcome['rows']} rows ingested")
        else:
            logger.error(f"✗ {name} {status}: {error_msg}")
            all_ok = False

        if fresh.get("fresh") is False:
            print(
                f"STALE {name}: newest row {fresh.get('source_max_date')} "
                f"is {fresh.get('age_days')} days old (limit {fresh.get('max_age_days')})"
            )

        results.append(
            {
                "name": name,
                "status": status,
                "duration_ms": outcome["duration_ms"],
                "row_count": int(outcome["rows"]),
                "error": error_msg,
                "fresh": fresh.get("fresh"),
                "source_max_date": fresh.get("source_max_date"),
            }
        )

        if collector:
            try:
                collector.add_ingester_result(
                    ingester_name=name,
                    status=status,
                    duration_ms=outcome["duration_ms"],
                    row_count=int(outcome["rows"]),
                    error_msg=error_msg,
                )
            except Exception as collector_error:
                logger.warning(f"Could not log to metrics: {collector_error}")

    # Print summary
    print(f"\n{'='*70}")
    print("INGESTION SUMMARY")
    print(f"{'='*70}")
    success_count = sum(1 for r in results if r["status"] == "success")
    fail_count = sum(1 for r in results if r["status"] in ("failed", "timeout"))
    stale_count = sum(1 for r in results if r.get("fresh") is False)
    skipped_count = sum(1 for r in results if r["status"] == "skipped")
    print(
        f"Total: {len(results)} | Success: {success_count} | Failed: {fail_count} "
        f"| Stale: {stale_count} | Skipped: {skipped_count}\n"
    )

    icons = {"success": "OK", "failed": "FAIL", "timeout": "TIME", "skipped": "SKIP"}
    for result in results:
        print(
            f"{icons.get(result['status'], '????'):<5}{result['name']:32} {result['status']:8} "
            f"({result['duration_ms']:6.0f}ms, {result['row_count']:6} rows)"
        )
        if result["error"]:
            print(f"      └─ Error: {result['error']}")
        if result.get("fresh") is False:
            print(f"      └─ Stale: newest row {result.get('source_max_date')}")

    print(f"\n{'='*70}")
    if all_ok:
        logger.info("All ingesters completed (staleness is reported, not retried)")
    else:
        logger.warning("Some ingesters failed - check logs above")

    return all_ok, results


def main():
    """Entry point for command-line usage."""
    # Line buffering so the startup script sees progress (and keeps it if the
    # outer timeout kills us).
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    # Rotate old logs before starting ingestion
    rotate_logs()

    parser = argparse.ArgumentParser(
        description="Run data ingesters by frequency (respects Monday schedule for weekly tasks)"
    )
    parser.add_argument(
        "--frequency",
        choices=["daily", "weekly", "monthly", "all"],
        default="all",
        help="Ingestion frequency to run (default: all)",
    )
    parser.add_argument(
        "--force-weekly",
        action="store_true",
        help="Force weekly ingesters to run even if not Monday",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore the ledger and rerun every ingester in the frequency",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Do not skip ingesters that already succeeded in this window",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Per-ingester timeout override in seconds (testing/manual runs)",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="Run a single ingester by module name (e.g. data_ingest.ingest_congress_bills_expanded)",
    )
    args = parser.parse_args()

    all_ok, results = run_all(
        args.frequency,
        force_weekly=args.force_weekly,
        resume=not args.no_resume,
        force=args.force,
        timeout_override=args.timeout,
        only=args.only,
    )

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
