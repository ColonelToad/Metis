#!/usr/bin/env python3
"""
Quick test of metrics collection integration
Run this to verify run_all_ingesters and orchestrate_daily_pipeline are collecting metrics

Usage:
    python test_metrics_integration.py
    
Then query:
    python -m research.metrics_cli recent --limit 5
    python -m research.metrics_cli health --days 7
"""

import sys
import os
from pathlib import Path

# Add research to path
sys.path.insert(0, str(Path(__file__).parent))

def test_ingester_metrics():
    """Test that run_all_ingesters collects per-ingester metrics"""
    print("\n" + "="*60)
    print("TEST 1: Ingester Metrics Collection")
    print("="*60)
    
    from research.metrics import MetricsCollector
    from research.data_ingest.run_all_ingesters import run_all
    
    # Create collector and run ingesters
    collector = MetricsCollector()
    run_id = collector.start_run(environment="DEV")
    print(f"Started run: {run_id}")
    
    # Run only daily ingesters (faster)
    ok, results = run_all(frequency="daily", collector=collector)
    
    # Finalize
    collector.finalize_run(status="success" if ok else "partial")
    
    print(f"\nResults:")
    print(f"  Overall success: {ok}")
    print(f"  Ingesters run: {len(results)}")
    for result in results:
        print(f"    {result['name'][:30]:30} | {result['status']:8} | {result['duration_ms']:8.0f}ms | {result['row_count']:6} rows")
    
    # Query back what was stored
    print(f"\nVerifying metrics stored in DB...")
    stored_ingesters = collector.get_run_ingesters(run_id)
    print(f"  Stored {len(stored_ingesters)} ingester results in DB")
    for ing in stored_ingesters[:3]:  # Show first 3
        print(f"    {ing['ingester_name']}: {ing['status']} ({ing['duration_ms']:.0f}ms)")


def test_pipeline_metrics():
    """Test that orchestrate_daily_pipeline collects phase metrics"""
    print("\n" + "="*60)
    print("TEST 2: Pipeline Metrics Collection")
    print("="*60)
    
    # Set DEV mode for synthetic data
    os.environ["METIS_MODE"] = "DEV"
    
    from research.orchestrate_daily_pipeline import main as pipeline_main
    
    result = pipeline_main()
    
    print(f"\nPipeline result:")
    print(f"  Status: {result['status']}")
    print(f"  Signals: {result['metrics']['signals_generated']}")
    print(f"  Total time: {result['metrics']['total_time']:.2f}s")
    print(f"  Metrics run_id: {result['metrics']['metrics_run_id']}")
    print(f"\nPhase timings:")
    print(f"  Ingest:    {result['metrics']['ingest_time']:.3f}s")
    print(f"  Features:  {result['metrics']['feature_time']:.3f}s")
    print(f"  Inference: {result['metrics']['inference_time']:.3f}s")
    
    # Query back
    print(f"\nVerifying metrics stored in DB...")
    from research.metrics import MetricsCollector
    collector = MetricsCollector()
    run_id = result['metrics']['metrics_run_id']
    stored_metrics = collector.get_run_metrics(run_id)
    print(f"  Stored {len(stored_metrics)} metrics in DB:")
    for name, value in sorted(stored_metrics.items()):
        print(f"    {name}: {value:.1f}")


def test_query_metrics():
    """Test querying metrics using CLI interface"""
    print("\n" + "="*60)
    print("TEST 3: Query Metrics")
    print("="*60)
    
    from research.metrics import MetricsCollector
    
    collector = MetricsCollector()
    
    # Show recent runs
    recent = collector.get_recent_runs(limit=5)
    print(f"\nRecent runs ({len(recent)} found):")
    for run in recent:
        print(f"  {run['run_id'][-20:]:20} | {run['environment']:4} | {run['status']}")
    
    # Show health
    health = collector.get_ingester_health(days=7)
    print(f"\nIngester health (last 7 days):")
    if health:
        for name, stats in sorted(health.items())[:5]:  # Show first 5
            print(f"  {name[:30]:30} | {stats['successful']:3}/{stats['total']:3} | {stats['success_rate']*100:5.1f}%")
    else:
        print("  (no data yet)")
    
    # Show trends
    print(f"\nMetric trends (last 7 days):")
    trend = collector.get_metric_trend("pipeline_total_ms", days=7)
    if trend:
        print(f"  pipeline_total_ms has {len(trend)} data points")
        if len(trend) > 1:
            values = [t['value'] for t in trend]
            print(f"    Min: {min(values):.1f}ms, Max: {max(values):.1f}ms")
    else:
        print("  (no data yet)")


if __name__ == "__main__":
    print("\nMetrics Integration Test Suite")
    print("="*60)
    
    try:
        test_ingester_metrics()
        test_pipeline_metrics()
        test_query_metrics()
        
        print("\n" + "="*60)
        print("✓ All tests passed!")
        print("="*60)
        print("\nNext: Query metrics using CLI")
        print("  python -m research.metrics_cli recent --limit 5")
        print("  python -m research.metrics_cli health --days 7")
        print("  python -m research.metrics_cli trend pipeline_total_ms --days 7")
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
