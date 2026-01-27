#!/usr/bin/env python3
"""
Metis Data Ingestion Wrapper
Runs all ingestion tasks with proper environment setup
"""
import sys
import os
from pathlib import Path
from datetime import datetime

# Setup paths
RESEARCH_DIR = Path(__file__).parent / "research"
DATA_INGEST_DIR = RESEARCH_DIR / "data_ingest"

# Add to Python path
sys.path.insert(0, str(RESEARCH_DIR))
sys.path.insert(0, str(DATA_INGEST_DIR))

# Load environment
from dotenv import load_dotenv
env_file = RESEARCH_DIR / ".env"
if env_file.exists():
    load_dotenv(env_file)

# Now we can import
print(f"[{datetime.now().isoformat()}] Starting ingestion...")

try:
    # Import here after paths are set
    from data_ingest import run_all_ingesters
    
    # Run
    run_all_ingesters.run_all()
    sys.exit(0)
    
except ImportError as e:
    print(f"Import error: {e}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)
