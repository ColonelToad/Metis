#!/usr/bin/env python3
"""
Data Ingestion Profiler - Detailed API Latency Analysis

Profiles individual API calls to identify:
- Which data sources are slowest
- Parallelization potential
- Cache hit rate (if applicable)
- Dependencies between data sources

Runs ingestion both sequentially and in parallel to show opportunity.

Usage:
    python profile_ingestion_detail.py

Output:
    - Per-API latency
    - Sequential vs parallel time comparison
    - Bottleneck identification
    - Cache effectiveness
"""

import os
import sys
import time
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Tuple, Any, Coroutine
import json

# Add workspace root to path (3 levels up: profiling -> research -> Metis)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from research.data_ingest import (
    ingest_eia, ingest_lmp, ingest_fred, ingest_bls_ppi,
    ingest_fred_building_permits, ingest_freight, ingest_cme_futures,
    ingest_congress_bills_expanded
)
from research.common import runtime_config as rc


class IngestionProfiler:
    """Profile data ingestion layer in detail"""
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.results = {}
        
        print(f"\n{'='*80}")
        print(f"DATA INGESTION PROFILER - {datetime.now().isoformat()}")
        print(f"Mode: {rc.mode_label()}")
        print(f"{'='*80}\n")
    
    def _log(self, msg: str):
        if self.verbose:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"[{ts}] {msg}")
    
    def _time_call(self, name: str, fn, *args, **kwargs) -> Tuple[Any, float]:
        """Time a single function call"""
        self._log(f"  Starting {name}...")
        start = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
            duration = time.perf_counter() - start
            self._log(f"  [OK] {name}: {duration:.3f}s")
            return result, duration
        except Exception as e:
            duration = time.perf_counter() - start
            self._log(f"  [FAIL] {name} FAILED after {duration:.3f}s: {str(e)[:60]}")
            return None, duration
    
    # =========================================================================
    # API FETCHERS (Wrapped for Timing)
    # =========================================================================
    
    def fetch_eia(self) -> Tuple[Dict, float]:
        """Fetch EIA data"""
        def combined_fetch():
            storage = ingest_eia.fetch_ng_storage()
            production = ingest_eia.fetch_ng_production()
            return {"storage": storage, "production": production}
        
        result, duration = self._time_call("EIA (storage + production)", combined_fetch)
        self.results["eia"] = {
            "duration": duration,
            "status": "ok" if result else "failed"
        }
        return result, duration
    
    def fetch_lmp(self) -> Tuple[Any, float]:
        """Fetch LMP data"""
        def lmp_fetch():
            from gridstatus import CAISO
            # 7-day lookback
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)
            
            caiso = CAISO()
            df = caiso.get_lmp(
                date=start_date,
                end=end_date,
                market="REAL_TIME_5_MIN"
            )
            return df
        
        result, duration = self._time_call("LMP/CAISO", lmp_fetch)
        self.results["lmp"] = {
            "duration": duration,
            "status": "ok" if result is not None else "failed"
        }
        return result, duration
    
    def fetch_fred(self) -> Tuple[Any, float]:
        """Fetch FRED data"""
        result, duration = self._time_call("FRED indicators", ingest_fred.main)
        self.results["fred"] = {
            "duration": duration,
            "status": "ok" if result else "failed"
        }
        return result, duration
    
    def fetch_congress(self) -> Tuple[Any, float]:
        """Fetch Congress data"""
        result, duration = self._time_call(
            "Congress bills",
            ingest_congress_bills_expanded.main
        )
        self.results["congress"] = {
            "duration": duration,
            "status": "ok" if result is not None else "failed"
        }
        return result, duration
    
    def fetch_bls(self) -> Tuple[Any, float]:
        """Fetch BLS data"""
        result, duration = self._time_call("BLS PPI", ingest_bls_ppi.main)
        self.results["bls"] = {
            "duration": duration,
            "status": "ok" if result is not None else "failed"
        }
        return result, duration
    
    def fetch_cme(self) -> Tuple[Any, float]:
        """Fetch CME futures"""
        result, duration = self._time_call("CME Futures", ingest_cme_futures.ingest_cme_futures)
        self.results["cme"] = {
            "duration": duration,
            "status": "ok" if result is not None else "failed"
        }
        return result, duration
    
    def fetch_freight(self) -> Tuple[Any, float]:
        """Fetch freight data"""
        result, duration = self._time_call("Freight data", ingest_freight.ingest_freight)
        self.results["freight"] = {
            "duration": duration,
            "status": "ok" if result is not None else "failed"
        }
        return result, duration
    
    # =========================================================================
    # SEQUENTIAL PROFILING (Current Behavior)
    # =========================================================================
    
    def profile_sequential(self) -> float:
        """Profile sequential execution (current behavior)"""
        print(f"\n{'-'*80}")
        print(f"SEQUENTIAL EXECUTION (Current Behavior)")
        print(f"{'-'*80}\n")
        
        start_total = time.perf_counter()
        
        self.fetch_eia()
        self.fetch_lmp()
        self.fetch_fred()
        self.fetch_congress()
        self.fetch_bls()
        self.fetch_cme()
        self.fetch_freight()
        
        sequential_time = time.perf_counter() - start_total
        return sequential_time
    
    # =========================================================================
    # PARALLEL PROFILING (Future Potential)
    # =========================================================================
    
    async def fetch_eia_async(self) -> Tuple[Dict, float]:
        """Async wrapper for EIA"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.fetch_eia)
    
    async def fetch_lmp_async(self) -> Tuple[Any, float]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.fetch_lmp)
    
    async def fetch_fred_async(self) -> Tuple[Any, float]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.fetch_fred)
    
    async def fetch_congress_async(self) -> Tuple[Any, float]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.fetch_congress)
    
    async def fetch_bls_async(self) -> Tuple[Any, float]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.fetch_bls)
    
    async def fetch_cme_async(self) -> Tuple[Any, float]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.fetch_cme)
    
    async def fetch_freight_async(self) -> Tuple[Any, float]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.fetch_freight)
    
    async def profile_parallel_async(self) -> float:
        """Profile parallel execution (future potential)"""
        print(f"\n{'-'*80}")
        print(f"PARALLEL EXECUTION (Future Potential with asyncio)")
        print(f"{'-'*80}\n")
        
        # Reset results for fresh timing
        self.results = {}
        
        start_total = time.perf_counter()
        
        # Run all concurrently
        await asyncio.gather(
            self.fetch_eia_async(),
            self.fetch_lmp_async(),
            self.fetch_fred_async(),
            self.fetch_congress_async(),
            self.fetch_bls_async(),
            self.fetch_cme_async(),
            self.fetch_freight_async(),
        )
        
        parallel_time = time.perf_counter() - start_total
        return parallel_time
    
    def profile_parallel(self) -> float:
        """Wrapper for parallel profiling"""
        return asyncio.run(self.profile_parallel_async())
    
    # =========================================================================
    # ANALYSIS & REPORTING
    # =========================================================================
    
    def print_summary(self, sequential_time: float, parallel_time: float):
        """Print comprehensive summary"""
        print(f"\n{'='*80}")
        print(f"INGESTION PROFILING SUMMARY")
        print(f"{'='*80}\n")
        
        # Timing comparison
        print(f"EXECUTION TIME COMPARISON:")
        print(f"{'-'*80}")
        print(f"  Sequential (current):  {sequential_time:>8.3f}s")
        print(f"  Parallel (potential):  {parallel_time:>8.3f}s")
        
        if parallel_time > 0:
            speedup = sequential_time / parallel_time
            savings = sequential_time - parallel_time
            print(f"  {'-'*80}")
            print(f"  Potential Speedup:     {speedup:>8.1f}x faster")
            print(f"  Time Saved:            {savings:>8.3f}s ({savings/sequential_time*100:.1f}%)")
        
        # Per-API breakdown
        print(f"\nPER-API LATENCY:")
        print(f"{'-'*80}")
        
        if self.results:
            sorted_apis = sorted(
                self.results.items(),
                key=lambda x: x[1].get("duration", 0),
                reverse=True
            )
            
            total_api_time = sum(r.get("duration", 0) for _, r in self.results.items())
            max_duration = max((r.get("duration", 0) for _, r in self.results.items()), default=1)
            
            for api_name, timing_info in sorted_apis:
                duration = timing_info.get("duration", 0)
                status = timing_info.get("status", "unknown")
                pct = (duration / total_api_time) * 100 if total_api_time > 0 else 0
                
                # Visual bar
                bar_len = int((duration / max_duration) * 30) if max_duration > 0 else 0
                bar = "=" * bar_len if status == "ok" else "X"
                
                status_icon = "[OK]" if status == "ok" else "[FAIL]"
                print(f"  {status_icon} {api_name:<25} {duration:>7.3f}s ({pct:>5.1f}%) {bar}")
        
        # Parallelization potential
        print(f"\nPARALLELIZATION POTENTIAL:")
        print(f"{'-'*80}")
        
        if self.results and parallel_time > 0:
            longest_api_time = max(
                (r.get("duration", 0) for _, r in self.results.items()),
                default=0
            )
            
            print(f"  Current bottleneck: Slowest API = {longest_api_time:.3f}s")
            
            # Even with perfect parallelization, limited by slowest API
            ideal_parallel = longest_api_time
            
            print(f"  Best case parallel: {ideal_parallel:.3f}s (limited by slowest)")
            print(f"  Theoretical speedup: {sequential_time / ideal_parallel:.1f}x")
            
            # Identify which API is the bottleneck
            if self.results:
                slowest = max(
                    self.results.items(),
                    key=lambda x: x[1].get("duration", 0)
                )
                print(f"  Bottleneck: {slowest[0]} ({slowest[1].get('duration', 0):.3f}s)")
        
        # Recommendations
        print(f"\nRECOMMENDATIONS:")
        print(f"{'-'*80}")
        
        if sequential_time > 0:
            if parallel_time > 0 and sequential_time / parallel_time > 2:
                print(f"  [YES] Parallelization HIGHLY RECOMMENDED")
                print(f"    Implementation: Convert run_all_ingesters.py to asyncio")
                print(f"    Expected benefit: {sequential_time / parallel_time:.1f}x faster ingestion")
            else:
                print(f"  • Parallelization has limited benefit (APIs run in parallel already)")
        
        print(f"\n{'='*80}\n")


def main():
    profiler = IngestionProfiler(verbose=True)
    
    # Profile both modes
    sequential_time = profiler.profile_sequential()
    
    print(f"\nWaiting before parallel run...")
    time.sleep(1)  # Brief pause between runs
    
    try:
        parallel_time = profiler.profile_parallel()
    except Exception as e:
        print(f"\n⚠ Parallel profiling failed: {e}")
        print(f"  (This may be expected if APIs don't support concurrent requests)")
        parallel_time = sequential_time
    
    profiler.print_summary(sequential_time, parallel_time)


if __name__ == "__main__":
    main()
