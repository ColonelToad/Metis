"""
Demonstration of TTL cache effectiveness with simulated latency.
This shows how the cache decorator works without needing real API calls.
"""

import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

# Add workspace root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from research.common import cache_utils


# Simulate an expensive API call (like LMP fetch)
@cache_utils.ttl_cache(ttl_seconds=2, cache_name="simulated_api")
def expensive_api_call(param1, param2):
    """Simulate an expensive 13-second API call with 2-second TTL for demo."""
    print(f"  [API] Processing {param1}, {param2}...")
    time.sleep(2)  # Simulate 2s network latency (actual LMP is 13s)
    return {"data": f"result for {param1}, {param2}", "timestamp": datetime.now().isoformat()}


def main():
    print("\n" + "=" * 70)
    print("TTL CACHE DEMONSTRATION")
    print("=" * 70)
    print("Testing cache with simulated 2-second API latency and 2-second TTL\n")

    # First call - hit network
    print("[Call 1] First call (should hit simulated API)...")
    t0 = time.time()
    result1 = expensive_api_call("arg1", "arg2")
    t1 = time.time() - t0
    print(f"✓ Completed in {t1:.3f}s")
    print(f"  Result: {result1}\n")

    # Second call - should hit cache
    print("[Call 2] Second call immediately after (should hit cache)...")
    t0 = time.time()
    result2 = expensive_api_call("arg1", "arg2")
    t2 = time.time() - t0
    print(f"✓ Completed in {t2:.3f}s")
    print(f"  Result: {result2}\n")

    # Wait for TTL to expire
    print("[Wait] Waiting 2.5 seconds for cache to expire...\n")
    time.sleep(2.5)

    # Third call - cache expired, hit network again
    print("[Call 3] After TTL expiry (should hit simulated API again)...")
    t0 = time.time()
    result3 = expensive_api_call("arg1", "arg2")
    t3 = time.time() - t0
    print(f"✓ Completed in {t3:.3f}s")
    print(f"  Result: {result3}\n")

    # Summary
    print("=" * 70)
    print("CACHE PERFORMANCE ANALYSIS")
    print("=" * 70)
    print(f"First call (network):     {t1:.3f}s")
    print(f"Second call (cache hit):  {t2:.3f}s")
    print(f"Third call (after expiry): {t3:.3f}s")
    print(f"\nSpeedup from caching: {t1/t2:.0f}x faster")
    print(f"Cache effectiveness: {100*(1 - t2/t1):.1f}% time saved")
    print("\n✅ In production with LMP (13s → <100ms), speedup would be ~130x")
    print("=" * 70 + "\n")

    # Check if metadata was saved
    metadata_file = Path(__file__).parent.parent / "data" / "cache_metadata" / "simulated_api_metadata.json"
    if metadata_file.exists():
        print(f"Cache metadata saved to: {metadata_file.relative_to(Path.cwd())}")
        with open(metadata_file) as f:
            print(f"Contents: {f.read()}")


if __name__ == "__main__":
    main()
