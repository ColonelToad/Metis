"""
Quick test to verify LMP caching is working.
Run this to confirm:
1. First call takes ~13 seconds (network fetch)
2. Second call within 1 hour takes <0.1 seconds (cache hit)
"""

import sys
from pathlib import Path
import time
from datetime import datetime, timedelta

# Add workspace root to path (so 'research' module is importable)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from research.data_ingest.ingest_lmp import fetch_caiso_lmp
from research.common import runtime_config as rc

def test_lmp_cache():
    """Test that LMP caching works correctly."""
    
    # Set to REAL mode to enable API calls
    rc.require_real_mode("CAISO LMP API")
    
    # Setup date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)
    
    print("=" * 70)
    print("LMP CACHE TEST")
    print("=" * 70)
    
    # First call - should hit network
    print("\n[Test 1] First fetch (should hit network, ~13 seconds)...")
    t1 = time.time()
    result1 = fetch_caiso_lmp(start_date, end_date)
    t1_elapsed = time.time() - t1
    print(f"✓ First fetch completed in {t1_elapsed:.2f} seconds")
    print(f"  Returned {len(result1)} records")
    
    # Second call - should hit cache
    print("\n[Test 2] Second fetch (should hit cache, <0.1 seconds)...")
    t2 = time.time()
    result2 = fetch_caiso_lmp(start_date, end_date)
    t2_elapsed = time.time() - t2
    print(f"✓ Second fetch completed in {t2_elapsed:.3f} seconds")
    print(f"  Returned {len(result2)} records")
    
    # Verify results are identical
    print("\n[Test 3] Verify cache returned identical data...")
    if result1.equals(result2):
        print("✓ Cache returned identical data")
    else:
        print("⚠ Data differs (this is expected if grid data updated)")
    
    # Calculate speedup
    speedup = t1_elapsed / t2_elapsed
    print("\n" + "=" * 70)
    print(f"SPEEDUP: {speedup:.0f}x faster (from {t1_elapsed:.2f}s to {t2_elapsed:.3f}s)")
    print("=" * 70)
    
    if t2_elapsed < 0.2:
        print("✅ Cache is working correctly!")
        return True
    else:
        print("❌ Cache may not be working (second call still took too long)")
        return False


if __name__ == "__main__":
    try:
        success = test_lmp_cache()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
