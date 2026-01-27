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
import ingest_congress_trades
import ingest_job_postings
import ingest_ais_maritime

# New data sources (Sprint Jan 27)
import ingest_freight
import ingest_aviation_fuel
import ingest_reddit_sentiment
import ingest_equities_simfin
import ingest_cme_futures

INGESTERS = [
    # Existing ingesters
    ("EIA Natural Gas", ingest_eia),
    ("Grid LMP", ingest_lmp),
    ("FRED Macro", ingest_fred),
    ("Congressional Trades", ingest_congress_trades),
    ("Job Postings", ingest_job_postings),
    ("Maritime AIS", ingest_ais_maritime),
    
    # New data sources (Sprint Jan 27)
    ("Freight Data", ingest_freight),
    ("Aviation Fuel", ingest_aviation_fuel),
    ("Reddit Sentiment", ingest_reddit_sentiment),
    ("SimFin Equities", ingest_equities_simfin),
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
            # Call the main ingest function if it exists
            if name == "Freight Data":
                module.ingest_freight()
            elif name == "Aviation Fuel":
                module.ingest_aviation_fuel()
            elif name == "Reddit Sentiment":
                module.ingest_reddit_sentiment()
            elif name == "SimFin Equities":
                module.ingest_equities()
            elif name == "CME Futures":
                module.ingest_cme_futures()
            else:
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
        status_str = "✓" if "SUCCESS" in status else "✗"
        print(f"{status_str} {name:30} {status}")
