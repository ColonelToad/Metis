"""
Run all data ingesters in sequence
For scheduled daily execution
"""
import sys
import os
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
import ingest_congress_bills_expanded
import ingest_bls_ppi
import ingest_fred_building_permits
import ingest_freight
import ingest_aviation_fuel
import ingest_cme_futures

INGESTERS = [
    # Existing ingesters (daily)
    ("EIA Natural Gas", ingest_eia, False),
    ("Grid LMP", ingest_lmp, False),
    ("FRED Macro", ingest_fred, False),
    ("Congress Bills", ingest_congress_bills_expanded, False),
    
    # Economic Indicators (daily)
    ("BLS Producer Price Index", ingest_bls_ppi, False),
    ("FRED Building Permits", ingest_fred_building_permits, False),
    
    # Data sources (daily)
    ("Freight Data", ingest_freight, False),
    ("CME Futures", ingest_cme_futures, False),
    
    # One-time ingesters (skip if already populated)
    ("Aviation Fuel", ingest_aviation_fuel, True),  # One-time: static historical data
]

def table_exists_with_data(table_name: str, min_records: int = 100) -> bool:
    """Check if table exists in database and has minimum records."""
    try:
        db_path = Path(__file__).parent.parent.parent / "data" / "metis.db"
        if not db_path.exists():
            return False
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        conn.close()
        
        return count >= min_records
    except Exception as e:
        # Table doesn't exist or query failed
        return False

def run_all():
    """Run all ingesters with error handling"""
    print(f"\n{'='*60}")
    print(f"Starting multi-source data ingestion: {datetime.now()}")
    print(f"{'='*60}\n")
    
    results = []
    
    for entry in INGESTERS:
        if len(entry) == 3:
            name, module, is_one_time = entry
        else:
            name, module = entry
            is_one_time = False
        
        # Skip one-time ingesters if already populated
        if is_one_time:
            table_name = {
                "Aviation Fuel": "aviation_fuel",
            }.get(name)
            
            if table_name and table_exists_with_data(table_name):
                print(f"\n--- Skipping {name} (already populated) ---")
                results.append((name, "SKIPPED (already in DB)"))
                continue
        
        try:
            print(f"\n--- Running {name} ingester ---")
            # Call the main/ingest function
            if name == "Freight Data":
                module.ingest_freight()
            elif name == "Aviation Fuel":
                module.ingest_aviation_fuel()
            elif name == "CME Futures":
                module.ingest_cme_futures()
            else:
                # For all others, use main() if available
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
