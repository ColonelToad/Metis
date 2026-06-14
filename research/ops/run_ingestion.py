#!/usr/bin/env python3
"""
Metis Data Ingestion Wrapper
Handles Python path setup and runs all ingesters
"""
import sys
from pathlib import Path

# Add research dir to path so all modules can import from 'research' namespace
research_dir = Path(__file__).parent.parent
sys.path.insert(0, str(research_dir))

# Now run ingesters
if __name__ == "__main__":
    from data_ingest.run_all_ingesters import main
    sys.exit(main())
