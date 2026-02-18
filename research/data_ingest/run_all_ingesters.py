"""
Run data ingesters in sequence with frequency support.
Supports daily, weekly, and monthly scheduled execution.

Frequencies:
  - daily: EIA, LMP, FRED Macro, Weather, Maritime AIS (run every day)
  - weekly: CME Futures, Drought Monitor, EIA Jet Fuel (run once per week)
  - monthly: BLS PPI, FRED Building Permits, Congress Bills (run once per month)
  - all: run all above regardless of schedule
"""
import sys
import os
import argparse
import traceback
import time
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Optional, List, Tuple, Dict

# Add parent directory (research/) to Python path so we can import from data_ingest/
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import all ingesters using qualified paths
from data_ingest import ingest_eia
from data_ingest import ingest_lmp
from data_ingest import ingest_fred
from data_ingest import ingest_weather
from data_ingest import ingest_ais_maritime
from data_ingest import ingest_cme_futures
from data_ingest import ingest_drought
from data_ingest import ingest_congress_bills_expanded
from data_ingest import ingest_bls_ppi
from data_ingest import ingest_fred_building_permits
from data_ingest import ingest_eia_jet_fuel

# Define ingester groups by frequency
DAILY_INGESTERS = [
    ("EIA Natural Gas", ingest_eia),
    ("Grid LMP", ingest_lmp),
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
    """Return list of (name, module) tuples based on frequency."""
    if frequency == "daily":
        return DAILY_INGESTERS
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
    descriptions = {
        "daily": "Daily run (EIA, LMP, FRED Macro, Weather, Maritime AIS)",
        "weekly": "Weekly run (CME Futures, Drought Monitor, EIA Jet Fuel)",
        "monthly": "Monthly run (BLS PPI, FRED Building Permits, Congress Bills)",
        "all": "All ingesters"
    }
    return descriptions.get(frequency, frequency)

def run_all(frequency: str = "all", collector=None) -> Tuple[bool, List[Dict]]:
    """
    Run ingesters filtered by frequency.
    
    Args:
        frequency: 'daily', 'weekly', 'monthly', or 'all'
        collector: Optional MetricsCollector instance to log results
    
    Returns:
        (overall_success: bool, results: list of dicts with ingester status)
    """
    ingesters = get_ingesters_for_frequency(frequency)
    
    print(f"\n{'='*60}")
    print(f"Starting {get_frequency_description(frequency)}: {datetime.now()}")
    print(f"{'='*60}\n")
    
    results = []
    all_ok = True
    
    for name, module in ingesters:
        start_time = time.time()
        status = "success"
        error_msg = None
        row_count = 0
        
        try:
            print(f"\n--- Running {name} ingester ---")
            # Call the main() function for each ingester
            if hasattr(module, 'main'):
                result = module.main()
                # If ingester returns row count, use it; otherwise 0
                if isinstance(result, int):
                    row_count = result
            else:
                print(f"WARNING: No main() function found in {name}")
                status = "failed"
                error_msg = "No main() function"
                all_ok = False
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            print(f"ERROR in {name}: {e}")
            traceback.print_exc()
            status = "failed"
            error_msg = str(e)
            all_ok = False
            
            # Log to metrics collector if provided
            if collector:
                collector.add_ingester_result(
                    ingester_name=name,
                    status=status,
                    duration_ms=duration_ms,
                    row_count=0,
                    error_msg=error_msg
                )
            
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
            collector.add_ingester_result(
                ingester_name=name,
                status=status,
                duration_ms=duration_ms,
                row_count=row_count,
                error_msg=error_msg
            )
        
        results.append({
            "name": name,
            "status": status,
            "duration_ms": duration_ms,
            "row_count": row_count,
            "error": error_msg
        })
    
    # Print summary
    print(f"\n{'='*60}")
    print("Ingestion Summary:")
    print(f"{'='*60}")
    for result in results:
        status_str = "[OK]" if result["status"] == "success" else "[XX]"
        print(f"{status_str} {result['name']:30} {result['status']:8} ({result['duration_ms']:.0f}ms, {result['row_count']} rows)")
        if result["error"]:
            print(f"      Error: {result['error']}")
    
    return all_ok, results

def main():
    """Entry point for command-line usage."""
    parser = argparse.ArgumentParser(description="Run data ingesters by frequency")
    parser.add_argument(
        "--frequency",
        choices=["daily", "weekly", "monthly", "all"],
        default="all",
        help="Ingestion frequency to run (default: all)"
    )
    args = parser.parse_args()
    
    all_ok, results = run_all(args.frequency)
    sys.exit(0 if all_ok else 1)

if __name__ == "__main__":
    main()
