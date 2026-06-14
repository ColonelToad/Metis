#!/usr/bin/env python3
"""
Quick pre-flight check:
- Can import metrics module?
- Can import orchestrate_daily_pipeline?
- Can import run_all_ingesters?
- DB can be created?
"""

import sys
from pathlib import Path

# Add research to path
sys.path.insert(0, str(Path(__file__).parent))

print("Pre-flight checks:\n")

try:
    print("1. Importing metrics module...", end=" ")
    from research.metrics import MetricsCollector
    print("✓")
except Exception as e:
    print(f"✗ {e}")
    sys.exit(1)

try:
    print("2. Creating metrics DB...", end=" ")
    collector = MetricsCollector()
    print("✓")
except Exception as e:
    print(f"✗ {e}")
    sys.exit(1)

try:
    print("3. Importing orchestrate_daily_pipeline...", end=" ")
    from research.orchestrate_daily_pipeline import main as pipeline_main
    print("✓")
except Exception as e:
    print(f"✗ {e}")
    sys.exit(1)

try:
    print("4. Importing run_all_ingesters...", end=" ")
    from research.data_ingest.run_all_ingesters import run_all
    print("✓")
except Exception as e:
    print(f"✗ {e}")
    sys.exit(1)

try:
    print("5. Checking logs directory...", end=" ")
    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    print("✓")
except Exception as e:
    print(f"✗ {e}")
    sys.exit(1)

print("\n✓ All pre-flight checks passed!")
print("\nYou can now run:")
print("  python test_metrics_integration.py")
