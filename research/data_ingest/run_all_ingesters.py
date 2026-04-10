"""
Run data ingesters in sequence with frequency support.
Supports daily, weekly, and monthly scheduled execution.

Frequencies:
  - daily: EIA, LMP, FRED Macro, Weather, Maritime AIS (run every day)
  - weekly: CME Futures, Drought Monitor, EIA Jet Fuel (run Mondays only)
  - monthly: BLS PPI, FRED Building Permits, Congress Bills (run once per month)
  - all: run all above regardless of schedule

Environment:
  - METIS_MODE=PROD: Enable all real API calls (LMP ISOs, PJM)
  - METIS_MODE=DEV: Skip live API calls for development/testing
"""
import sys
import os
import argparse
import time
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Optional, List, Tuple, Dict
import logging

# Add parent directory (research/) to Python path so we can import from data_ingest/
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import all ingesters using qualified paths
from data_ingest import ingest_eia
from data_ingest import ingest_lmp
from data_ingest import ingest_lmp_multi_iso
from data_ingest import ingest_fred
from data_ingest import ingest_weather
from data_ingest import ingest_ais_maritime
from data_ingest import ingest_cme_futures
from data_ingest import ingest_drought
from data_ingest import ingest_congress_bills_expanded
from data_ingest import ingest_bls_ppi
from data_ingest import ingest_fred_building_permits
from data_ingest import ingest_eia_jet_fuel

# Import log rotation
from log_rotation import rotate_logs

# Import R2 uploader for post-ingestion backup
def backup_to_r2():
    """Upload database and cache to R2 after successful ingestion."""
    try:
        import subprocess
        from pathlib import Path
        
        # Run the comprehensive auto-backup script
        backup_script = Path(__file__).parent.parent / "r2_auto_backup.py"
        if not backup_script.exists():
            logger.warning(f"R2 backup script not found: {backup_script}")
            return
        
        logger.info("Running R2 backup...")
        result = subprocess.run(
            [__import__('sys').executable, str(backup_script)],
            cwd=Path(__file__).parent.parent.parent,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        # Log the backup output
        if result.stdout:
            for line in result.stdout.split('\n'):
                if line.strip():
                    logger.info(line)
        
        if result.returncode == 0:
            logger.info("✓ R2 backup completed successfully")
        else:
            logger.warning(f"⚠ R2 backup encountered issues (non-blocking)")
            if result.stderr:
                logger.warning(result.stderr)
    
    except Exception as e:
        logger.warning(f"R2 backup failed (non-critical): {e}")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
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
    ("Maritime AIS", ingest_ais_maritime),
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
]

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
        "daily": f"Daily run (EIA, LMP, Multi-ISO LMP, FRED, Weather, AIS)" + 
                 (f" + Weekly CME Futures (Monday)" if is_mon else ""),
        "weekly": "Weekly run (CME Futures, Drought Monitor, EIA Jet Fuel) - Runs Mondays",
        "monthly": "Monthly run (BLS PPI, FRED Building Permits, Congress Bills)",
        "all": "All ingesters (daily + weekly + monthly)"
    }
    return descriptions.get(frequency, frequency)

def run_all(frequency: str = "all", collector=None, force_weekly: bool = False) -> Tuple[bool, List[Dict]]:
    """
    Run ingesters filtered by frequency.
    
    Args:
        frequency: 'daily', 'weekly', 'monthly', or 'all'
        collector: Optional MetricsCollector instance to log results
        force_weekly: If True, run weekly ingesters even if not Monday
    
    Returns:
        (overall_success: bool, results: list of dicts with ingester status)
    """
    # Handle weekly scheduling for 'daily' frequency
    if frequency == "daily" and not is_monday():
        logger.info("Daily run scheduled (not Monday, skipping weekly ingesters)")
    
    ingesters = get_ingesters_for_frequency(frequency)
    
    print(f"\n{'='*70}")
    print(f"Starting {get_frequency_description(frequency)}: {datetime.now()}")
    print(f"Mode: {METIS_MODE} | Ingesters: {len(ingesters)}")
    print(f"{'='*70}\n")
    
    results = []
    all_ok = True
    
    for name, module in ingesters:
        start_time = time.time()
        status = "success"
        error_msg = None
        row_count = 0
        
        try:
            logger.info(f"Running {name} ingester")
            print(f"\n>>> {name} ingester")
            # Call the main() function for each ingester
            if hasattr(module, 'main'):
                result = module.main()
                # If ingester returns row count, use it; otherwise 0
                if isinstance(result, int):
                    row_count = result
                logger.info(f"✓ {name}: {row_count} rows ingested")
            else:
                logger.warning(f"No main() function found in {name}")
                status = "failed"
                error_msg = "No main() function"
                all_ok = False
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(f"✗ {name} failed: {e}", exc_info=True)
            print(f"ERROR in {name}: {e}")
            status = "failed"
            error_msg = str(e)
            all_ok = False
            
            # Log to metrics collector if provided
            if collector:
                try:
                    collector.add_ingester_result(
                        ingester_name=name,
                        status=status,
                        duration_ms=duration_ms,
                        row_count=0,
                        error_msg=error_msg
                    )
                except Exception as collector_error:
                    logger.warning(f"Could not log to metrics: {collector_error}")
            
            results.append({
                "name": name,
                "status": status,
                "duration_ms": duration_ms,
                "row_count": 0,
                "error": error_msg
            })
            continue
        
        duration_ms = (time.time() - start_time) * 1000
        
        # Log to metrics collector if provided
        if collector:
            try:
                collector.add_ingester_result(
                    ingester_name=name,
                    status=status,
                    duration_ms=duration_ms,
                    row_count=row_count,
                    error_msg=error_msg
                )
            except Exception as collector_error:
                logger.warning(f"Could not log to metrics: {collector_error}")
        
        results.append({
            "name": name,
            "status": status,
            "duration_ms": duration_ms,
            "row_count": row_count,
            "error": error_msg
        })
    
    # Print summary
    print(f"\n{'='*70}")
    print("INGESTION SUMMARY")
    print(f"{'='*70}")
    success_count = sum(1 for r in results if r["status"] == "success")
    fail_count = sum(1 for r in results if r["status"] == "failed")
    print(f"Total: {len(results)} | Success: {success_count} | Failed: {fail_count}\n")
    
    for result in results:
        status_icon = "✓" if result["status"] == "success" else "✗"
        print(f"{status_icon} {result['name']:30} {result['status']:8} ({result['duration_ms']:6.0f}ms, {result['row_count']:6} rows)")
        if result["error"]:
            print(f"  └─ Error: {result['error']}")
    
    print(f"\n{'='*70}")
    if all_ok:
        logger.info(f"All ingesters completed successfully")
    else:
        logger.warning(f"Some ingesters failed - check logs above")
    
    return all_ok, results

def main():
    """Entry point for command-line usage."""
    # Rotate old logs before starting ingestion
    rotate_logs()
    
    parser = argparse.ArgumentParser(
        description="Run data ingesters by frequency (respects Monday schedule for weekly tasks)"
    )
    parser.add_argument(
        "--frequency",
        choices=["daily", "weekly", "monthly", "all"],
        default="all",
        help="Ingestion frequency to run (default: all)"
    )
    parser.add_argument(
        "--force-weekly",
        action="store_true",
        help="Force weekly ingesters to run even if not Monday"
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip R2 backup after ingestion"
    )
    args = parser.parse_args()
    
    all_ok, results = run_all(args.frequency, force_weekly=args.force_weekly)
    
    # Backup to R2 after successful ingestion (unless --no-backup is set)
    if all_ok and not args.no_backup:
        logger.info("Ingestion completed successfully, starting R2 backup...")
        backup_to_r2()
    
    sys.exit(0 if all_ok else 1)

if __name__ == "__main__":
    main()
