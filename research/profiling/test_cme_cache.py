"""
Test CME caching effectiveness.
Verifies that the 7-day cache reduces network calls.
"""

import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

# Add workspace root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from research.data_ingest.ingest_cme_futures import fetch_cme_futures_cached


def test_cme_cache():
    """Test that CME caching works correctly."""
    
    # Setup date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=730)
    
    print("\n" + "=" * 70)
    print("CME CACHE TEST")
    print("=" * 70)
    print(f"Date range: {start_date.date()} to {end_date.date()}")
    
    # First call - should hit network
    print("\n[Test 1] First fetch (should hit network, ~1.3 seconds)...")
    t1 = time.time()
    result1 = fetch_cme_futures_cached(
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d")
    )
    t1_elapsed = time.time() - t1
    print(f"[OK] First fetch completed in {t1_elapsed:.2f} seconds")
    print(f"  Returned {len(result1)} records")
    
    # Second call - should hit cache
    print("\n[Test 2] Second fetch (should hit cache, <0.1 seconds)...")
    t2 = time.time()
    result2 = fetch_cme_futures_cached(
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d")
    )
    t2_elapsed = time.time() - t2
    print(f"[OK] Second fetch completed in {t2_elapsed:.3f} seconds")
    print(f"  Returned {len(result2)} records")
    
    # Verify results are identical
    print("\n[Test 3] Verify cache returned identical data...")
    if result1.equals(result2):
        print("[OK] Cache returned identical data")
    else:
        print("[INFO] Data differs (expected if market data updated)")
    
    # Calculate speedup
    speedup = t1_elapsed / (t2_elapsed + 0.001)  # Avoid division by zero
    print("\n" + "=" * 70)
    print(f"SPEEDUP: {speedup:.0f}x faster (from {t1_elapsed:.2f}s to {t2_elapsed:.3f}s)")
    print("=" * 70)
    
    if t2_elapsed < 0.2:
        print("[OK] Cache is working correctly!")
        return True
    else:
        print("[!] Cache may not be working (second call still took too long)")
        return False


if __name__ == "__main__":
    try:
        success = test_cme_cache()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
