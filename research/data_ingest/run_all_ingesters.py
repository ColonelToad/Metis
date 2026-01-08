"""
Run all data ingesters in sequence
For scheduled daily execution
"""
import sys
import traceback
from datetime import datetime

# Import all ingesters
import ingest_eia
import ingest_lmp
import ingest_fred
import ingest_congress_trades
import ingest_job_postings
import ingest_ais_maritime

INGESTERS = [
    ("EIA Natural Gas", ingest_eia),
    ("Grid LMP", ingest_lmp),
    ("FRED Macro", ingest_fred),
    ("Congressional Trades", ingest_congress_trades),
    ("Job Postings", ingest_job_postings),
    ("Maritime AIS", ingest_ais_maritime),
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
            module.main() if hasattr(module, 'main') else exec(open(module.__file__).read())
            results.append((name, "SUCCESS"))
        except Exception as e:
            print(f"ERROR in {name}: {e}")
            traceback.print_exc()
            results.append((name, f"FAILED: {str(e)}"))
    
    print(f"\n{'='*60}")
    print("Ingestion Summary:")
    print(f"{'='*60}")
    for name, status in results:
        print(f"{name:30} {status}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    run_all()
