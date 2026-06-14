#!/usr/bin/env python3
"""
Metis Data Ingestion Wrapper
Runs ingestion tasks with proper environment setup

Usage:
    python ingest_wrapper.py [--frequency {daily|weekly|monthly|all}]
    
Frequencies:
    daily   - EIA, LMP, FRED Macro, Weather
    weekly  - CME Futures, Drought Monitor
    monthly - BLS PPI, FRED Building Permits, Congress Bills
    all     - run all of the above (default)
"""
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime

# Setup paths
RESEARCH_DIR = Path(__file__).parent.parent
DATA_INGEST_DIR = RESEARCH_DIR / "data_ingest"

# Add to Python path
sys.path.insert(0, str(RESEARCH_DIR))
sys.path.insert(0, str(DATA_INGEST_DIR))

# Load environment
from dotenv import load_dotenv
env_file = RESEARCH_DIR.parent / ".env"
if env_file.exists():
    load_dotenv(env_file)

# Now we can import
print(f"[{datetime.now().isoformat()}] Starting ingestion...")

try:
    # Import here after paths are set
    from data_ingest import run_all_ingesters
    
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Run data ingesters by frequency")
    parser.add_argument(
        "--frequency",
        choices=["daily", "weekly", "monthly", "all"],
        default="all",
        help="Ingestion frequency to run (default: all)"
    )
    args = parser.parse_args()
    
    # Run with specified frequency
    run_all_ingesters.run_all(args.frequency)
    sys.exit(0)
    
except ImportError as e:
    print(f"Import error: {e}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)
