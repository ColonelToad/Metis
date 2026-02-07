"""
Run all data ingesters in sequence
For scheduled daily execution
"""
import sys
import os
import traceback
from datetime import datetime
from pathlib import Path

# Add parent directory (research/) to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import all ingesters
import ingest_eia
import ingest_lmp
import ingest_fred
import ingest_congress_bills_expanded
import ingest_ais_maritime
import ingest_bls_ppi
import ingest_fred_building_permits
import ingest_freight
import ingest_aviation_fuel
import ingest_cme_futures

INGESTERS = [
    # Existing ingesters
    ("EIA Natural Gas", ingest_eia),
    ("Grid LMP", ingest_lmp),
    ("FRED Macro", ingest_fred),
    ("Congress Bills", ingest_congress_bills_expanded),
    ("Maritime AIS", ingest_ais_maritime),
    
    # Economic Indicators
    ("BLS Producer Price Index", ingest_bls_ppi),
    ("FRED Building Permits", ingest_fred_building_permits),
    
    # New data sources (Sprint Jan 27)
    ("Freight Data", ingest_freight),
    ("Aviation Fuel", ingest_aviation_fuel),
    ("CME Futures", ingest_cme_futures),
]

def run_all():
    """Run all ingesters with error handling"""
    print(f"\n{'='*60}")
    print(f"Starting multi-source data ingestion: {datetime.now()}")
    print(f"{'='*60}\n")
    
    results = []
    
    for name, module in INGESTERS:
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
