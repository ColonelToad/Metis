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
from datetime import datetime
from pathlib import Path
import sqlite3

# Add parent directory (research/) to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import all ingesters
import ingest_eia
import ingest_lmp
import ingest_fred
import ingest_weather
import ingest_ais_maritime
import ingest_cme_futures
import ingest_drought
import ingest_congress_bills_expanded
import ingest_bls_ppi
import ingest_fred_building_permits
import ingest_eia_jet_fuel

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

def run_all(frequency: str = "all"):
    """
    Run ingesters filtered by frequency.
    
    Args:
        frequency: 'daily', 'weekly', 'monthly', or 'all'
    """
    ingesters = get_ingesters_for_frequency(frequency)
    
    print(f"\n{'='*60}")
    print(f"Starting {get_frequency_description(frequency)}: {datetime.now()}")
    print(f"{'='*60}\n")
    
    results = []
    
    for name, module in ingesters:
        try:
            print(f"\n--- Running {name} ingester ---")
            # Call the main() function for each ingester
            if hasattr(module, 'main'):
                module.main()
            else:
                print(f"WARNING: No main() function found in {name}")
                results.append((name, "FAILED: No main() function"))
                continue
            results.append((name, "SUCCESS"))
        except Exception as e:
            print(f"ERROR in {name}: {e}")
            traceback.print_exc()
            results.append((name, f"FAILED: {str(e)}"))
    
    print(f"\n{'='*60}")
    print("Ingestion Summary:")
    print(f"{'='*60}")
    for name, status in results:
        status_str = "[OK]" if "SUCCESS" in status else "[XX]"
        print(f"{status_str} {name:30} {status}")

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
    
    run_all(args.frequency)

if __name__ == "__main__":
    main()
