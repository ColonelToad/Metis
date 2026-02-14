"""
CME Futures Ingestion Profiler - Detailed Performance Analysis

Measures:
- Total CME ingestion time
- Per-contract time (NG, WTI, HO, RB)
- Data volume retrieved
- Parallelization potential
"""

import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

# Add workspace root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from research.data_ingest import ingest_cme_futures
from research.data_ingest.ingest_cme_futures import CMEFuturesClient


def profile_cme_ingestion():
    """Profile CME futures ingestion with detailed breakdown."""
    
    print("\n" + "=" * 70)
    print("CME FUTURES INGESTION PROFILER")
    print("=" * 70)
    
    ingestor = CMEFuturesClient()
    
    # Default date range (what it normally uses)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=730)  # 2 years
    
    print(f"\nDate Range: {start_date.date()} to {end_date.date()}")
    print(f"Lookback: {(end_date - start_date).days} days")
    print(f"Number of contracts: {len(ingest_cme_futures.CME_FUTURES)}")
    
    # Profile each contract individually
    print("\n" + "-" * 70)
    print("PER-CONTRACT TIMING")
    print("-" * 70)
    
    contract_timings = {}
    
    for contract_key, config in ingest_cme_futures.CME_FUTURES.items():
        symbol = config["symbol"]
        print(f"\n[{contract_key.upper()}] {symbol} ({config['name']})...")
        
        t0 = time.time()
        try:
            df = ingestor.fetch_futures(
                symbol, 
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d")
            )
            elapsed = time.time() - t0
            
            contract_timings[contract_key] = {
                'time': elapsed,
                'records': len(df),
                'success': True
            }
            
            print(f"  [OK] {len(df):>6} records | {elapsed:>7.3f}s")
        except Exception as e:
            elapsed = time.time() - t0
            contract_timings[contract_key] = {
                'time': elapsed,
                'records': 0,
                'success': False,
                'error': str(e)[:50]
            }
            print(f"  [FAIL] Error ({elapsed:.3f}s): {str(e)[:60]}")
    
    # Total timing
    total_time = sum(c['time'] for c in contract_timings.values())
    total_records = sum(c['records'] for c in contract_timings.values())
    
    print("\n" + "-" * 70)
    print("SUMMARY")
    print("-" * 70)
    print(f"\nTotal contracts:     {len(contract_timings)}")
    print(f"Total records:       {total_records:,}")
    print(f"Total time (seq):    {total_time:.3f}s")
    print(f"Avg time per API:    {total_time / len(contract_timings):.3f}s")
    
    # Parallelization potential
    max_contract_time = max(c['time'] for c in contract_timings.values())
    parallel_speedup = total_time / max_contract_time
    
    print(f"\nIf parallelized:     {max_contract_time:.3f}s (limited by slowest)")
    print(f"Max speedup potential: {parallel_speedup:.1f}x")
    
    # Analyze slowest contracts
    print("\n" + "-" * 70)
    print("SLOWEST CONTRACTS")
    print("-" * 70)
    
    sorted_by_time = sorted(contract_timings.items(), key=lambda x: x[1]['time'], reverse=True)
    for i, (contract, data) in enumerate(sorted_by_time[:3], 1):
        pct = (data['time'] / total_time * 100) if total_time > 0 else 0
        print(f"{i}. {contract:20} {data['time']:>7.3f}s ({pct:>5.1f}%) - {data['records']:>6} records")
    
    # Estimate impact of lookback reduction
    print("\n" + "-" * 70)
    print("LOOKBACK WINDOW ANALYSIS")
    print("-" * 70)
    print(f"\nCurrent lookback: {(end_date - start_date).days} days")
    print("Average per day:  {:.4f}s".format(total_time / (end_date - start_date).days))
    
    for lookback_days in [365, 180, 90, 30]:
        estimated_time = total_time * (lookback_days / (end_date - start_date).days)
        reduction_pct = ((total_time - estimated_time) / total_time * 100)
        print(f"  {lookback_days:>3} days: {estimated_time:.3f}s ({reduction_pct:>5.1f}% faster)")
    
    print("\n" + "=" * 70)
    print("RECOMMENDATIONS")
    print("=" * 70)
    
    if parallel_speedup > 1.3:
        print(f"\n[+] Parallelization would save {total_time - max_contract_time:.3f}s ({(1-1/parallel_speedup)*100:.1f}%)")
        print("  Action: Consider async API calls for multiple contracts")
    else:
        print(f"\n[-] Parallelization would save <{(1-1/parallel_speedup)*100:.1f}%")
        print("  Action: Not worth implementing - APIs already near-optimal")
    
    if total_time > 2.0:
        print(f"\n[!] CME ingestion is slow ({total_time:.2f}s)")
        print("  Consider:")
        print("  1. Reduce lookback window (1-2 years instead of 2)")
        print("  2. Cache CME data with 30-minute TTL")
        print("  3. Check if Yahoo Finance is responding slowly")
    
    print()
    return contract_timings, total_time


if __name__ == "__main__":
    timings, total = profile_cme_ingestion()
