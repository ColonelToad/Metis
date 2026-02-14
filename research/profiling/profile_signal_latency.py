#!/usr/bin/env python3
"""
End-to-End Signal Generation Latency Profiler

Measures the complete path from raw data to trading signal:
1. Current data fetch (what's in DB)
2. Feature engineering from raw data
3. Model inference
4. Signal generation
5. Execution bridge (if connected)

This is different from ingestion - it measures what happens when
you actually need to generate a signal RIGHT NOW.

Usage:
    python profile_signal_latency.py [--fresh-ingest]

    --fresh-ingest: Force re-ingestion of data (slower, but measures true latency)
"""

import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any
import json

# Add workspace root to path (3 levels up: profiling -> research -> Metis)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text

from research.features.engineer_features import FeatureEngineer, DB_URL
from research.common import runtime_config as rc


class SignalLatencyProfiler:
    """Profile end-to-end signal generation latency"""
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.timings = {}
        
        print(f"\n{'='*80}")
        print(f"SIGNAL GENERATION LATENCY PROFILER - {datetime.now().isoformat()}")
        print(f"Mode: {rc.mode_label()}")
        print(f"{'='*80}\n")
    
    def _log(self, msg: str, level: str = "INFO"):
        if self.verbose:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"[{ts}] {level:8s} {msg}")
    
    def _time_section(self, label: str, fn):
        """Time a section and log it"""
        self._log(f"Starting: {label}")
        start = time.perf_counter()
        result = fn()
        duration = time.perf_counter() - start
        self.timings[label] = duration
        self._log(f"Complete: {label} = {duration:.3f}s", "DONE")
        return result, duration
    
    def profile_signal_generation(self, fresh_ingest: bool = False) -> Dict[str, Any]:
        """Profile complete signal generation latency"""
        
        results = {
            "timestamp": datetime.now().isoformat(),
            "mode": rc.mode_label(),
            "fresh_ingest": fresh_ingest,
            "timings": {},
            "data_counts": {},
        }
        
        # Step 1: Get data (optionally fresh from APIs)
        if fresh_ingest:
            print(f"\nPhase 1: Fresh Data Ingestion (from APIs)")
            print(f"{'-'*80}\n")
            
            # Import the ingestion profiler
            from research.profiling.profile_ingestion_detail import IngestionProfiler
            ingest_profiler = IngestionProfiler(verbose=False)
            
            ingest_time = ingest_profiler.profile_sequential()
            self.timings["ingest_fresh"] = ingest_time
            results["timings"]["ingest_fresh"] = ingest_time
            
            self._log(f"Data ingestion completed in {ingest_time:.3f}s", "DONE")
        else:
            self._log(f"Using cached data from database (no fresh ingestion)", "INFO")
        
        # Step 2: Feature engineering
        print(f"\nPhase 2: Feature Engineering")
        print(f"{'-'*80}\n")
        
        fe = FeatureEngineer(DB_URL, start_date="2015-01-01")
        
        def load_and_engineer():
            """Load all features and engineer them"""
            df = fe.engineer_features()
            return df
        
        try:
            features_df, features_time = self._time_section(
                "engineer_features",
                load_and_engineer
            )
        except Exception as e:
            if "no such table" in str(e):
                self._log(
                    f"Database is empty (no data tables exist)",
                    "WARN"
                )
                results["error"] = "Database not populated yet"
                results["suggestion"] = "To populate with demo data: python run_ingestion.py"
                return results
            else:
                self._log(f"Feature engineering failed: {str(e)}", "ERROR")
                raise
        results["timings"]["engineer_features"] = features_time
        results["data_counts"]["feature_rows"] = len(features_df) if not features_df.empty else 0
        results["data_counts"]["feature_cols"] = len(features_df.columns) if not features_df.empty else 0
        
        # Get most recent features for actual inference
        if not features_df.empty:
            most_recent_feature_date = features_df['date'].max() if 'date' in features_df.columns else None
            self._log(f"Features ready: {features_df.shape[0]} rows × {features_df.shape[1]} cols", "DONE")
            self._log(f"Most recent date: {most_recent_feature_date}", "INFO")
        else:
            self._log(f"No features available", "WARN")
            most_recent_feature_date = None
        
        # Step 3: Model inference
        print(f"\nPhase 3: Model Inference")
        print(f"{'-'*80}\n")
        
        try:
            from research.models.inference_pipeline import DualLSTMInference
            
            # Initialize model
            def init_model():
                pipeline = DualLSTMInference(
                    model_path="models/lstm_ng_predictor.keras",
                    scalers_path="models/scalers_v1.0.pkl",
                    threshold=0.40,
                )
                return pipeline
            
            model, model_init_time = self._time_section(
                "model_init",
                init_model
            )
            results["timings"]["model_init"] = model_init_time
            
            # Prepare daily features
            def prep_daily():
                return fe.load_price_data()
            
            daily_df, daily_prep_time = self._time_section(
                "prep_daily_features",
                prep_daily
            )
            results["timings"]["prep_daily_features"] = daily_prep_time
            
            # Prepare low-frequency features
            def prep_lowfreq():
                return fe.load_eia_features(daily_df)
            
            low_freq_df, lowfreq_prep_time = self._time_section(
                "prep_lowfreq_features",
                prep_lowfreq
            )
            results["timings"]["prep_lowfreq_features"] = lowfreq_prep_time
            
            # Run inference
            def run_inference():
                prediction = model.predict(daily_df, low_freq_df, pd.DataFrame())
                return prediction
            
            prediction, inference_time = self._time_section(
                "model_predict",
                run_inference
            )
            results["timings"]["model_predict"] = inference_time
            results["prediction"] = prediction
            
            self._log(
                f"Prediction: {prediction['direction']} "
                f"(confidence={prediction['confidence']:.2%})",
                "DONE"
            )
            
        except FileNotFoundError as e:
            self._log(f"Model files not found: {e}", "WARN")
            self._log(f"(Expected if models haven't been trained yet)", "INFO")
            results["prediction"] = None
        except Exception as e:
            self._log(f"Model inference failed: {e}", "ERROR")
            results["prediction"] = None
        
        # Step 4: Signal generation
        print(f"\nPhase 4: Signal Generation")
        print(f"{'-'*80}\n")
        
        try:
            def create_signal():
                signal = model.prediction_to_signal(
                    prediction,
                    symbol="NG:CME",
                    target_quantity=10.0,
                    horizon_minutes=1440,  # 1 day
                )
                return signal
            
            signal, signal_gen_time = self._time_section(
                "signal_generation",
                create_signal
            )
            results["timings"]["signal_generation"] = signal_gen_time
            results["signal_generated"] = True
            
        except Exception as e:
            self._log(f"Signal generation failed: {e}", "ERROR")
            results["signal_generated"] = False
        
        # Summary timing
        print(f"\nPhase 5: Latency Summary")
        print(f"{'-'*80}\n")
        
        total_time = sum(
            v for k, v in self.timings.items()
            if k not in ["ingest_fresh"]  # Don't count ingestion in "signal latency"
        )
        
        print(f"LATENCY BREAKDOWN (excluding ingestion):\n")
        
        for label, duration in sorted(self.timings.items()):
            if label != "ingest_fresh":
                pct = (duration / total_time * 100) if total_time > 0 else 0
                bar = "█" * int(duration / max(self.timings.values().copy() or [1]) * 40) if self.timings else ""
                print(f"  {label:<30} {duration:>7.3f}s ({pct:>5.1f}%) {bar}")
        
        print(f"  {'-'*80}")
        print(f"  {'TOTAL (signal path)':<30} {total_time:>7.3f}s (100.0%)")
        
        if fresh_ingest:
            total_with_ingest = total_time + self.timings.get("ingest_fresh", 0)
            print(f"\n  + Data ingestion:            {self.timings.get('ingest_fresh', 0):>7.3f}s")
            print(f"  {'-'*80}")
            print(f"  {'TOTAL (end-to-end)':<30} {total_with_ingest:>7.3f}s")
        
        results["timings"]["total_signal_latency"] = total_time
        
        return results
    
    def print_analysis(self, results: Dict[str, Any]):
        """Print analysis and recommendations"""
        print(f"\n{'='*80}")
        print(f"ANALYSIS & RECOMMENDATIONS")
        print(f"{'='*80}\n")
        
        # Check for errors
        if "error" in results:
            print(f"[NOTE] {results['error']}\n")
            if "suggestion" in results:
                print(f"Suggestion: {results['suggestion']}\n")
                print(f"Example commands:")
                print(f"  $ cd C:\\Users\\legot\\Metis")
                print(f"  $ python research/run_ingestion.py      # Populate database")
                print(f"  $ cd research")
                print(f"  $ python profiling/profile_signal_latency.py  # Then profile")
            print(f"\n{'='*80}\n")
            return
        
        timings = results["timings"]
        total = timings.get("total_signal_latency", 0)
        
        if total == 0:
            print(f"No timing data available")
            return
        
        # Find bottlenecks
        print(f"BOTTLENECK IDENTIFICATION:\n")
        
        sorted_timings = sorted(
            [(k, v) for k, v in timings.items() if k != "total_signal_latency" and k != "ingest_fresh"],
            key=lambda x: x[1],
            reverse=True
        )
        
        for i, (label, duration) in enumerate(sorted_timings, 1):
            pct = (duration / total) * 100
            
            if pct > 50:
                level = "🔴 CRITICAL"
            elif pct > 30:
                level = "🟡 HIGH"
            elif pct > 10:
                level = "🟢 MEDIUM"
            else:
                level = "⚪ LOW"
            
            print(f"  {i}. {level} {label}")
            print(f"     {duration:.3f}s ({pct:.1f}% of signal latency)")
            
            # Give recommendations for top bottlenecks
            if i <= 2:
                if "engineer_features" in label:
                    print(f"     → Consider: Incremental updates, caching, vectorization")
                    print(f"     → Or: Move heavy transforms to Rust")
                elif "prep_" in label:
                    print(f"     → This is data loading/preprocessing")
                    print(f"     → Consider: Query optimization, indexing in database")
                elif "model_predict" in label:
                    print(f"     → Consider: Model quantization (FP16), ONNX runtime, batch processing")
                elif "signal_generation" in label:
                    print(f"     → This should be fast already (<1ms)")
                    print(f"     → If slow: Check for DB writes or network calls")
            
            print()
        
        # Realtime vs batch recommendations
        print(f"OPERATIONAL RECOMMENDATIONS:\n")
        
        signal_latency = timings.get("total_signal_latency", 0)
        ingest_latency = timings.get("ingest_fresh", 0)
        
        print(f"  For REAL-TIME signals (generated on-demand):")
        if signal_latency < 1.0:
            print(f"    ✓ GOOD: {signal_latency:.3f}s latency is acceptable (<1s)")
            print(f"    → Can generate signals immediately on request")
        elif signal_latency < 5.0:
            print(f"    ⚠ MODERATE: {signal_latency:.3f}s latency is borderline")
            print(f"    → Consider: Caching features, lazy loading non-essential data")
        else:
            print(f"    ✗ SLOW: {signal_latency:.3f}s latency is too high")
            print(f"    → Need optimization before real-time signals")
        
        print(f"\n  For BATCH signals (generated daily at scheduled time):")
        if ingest_latency > 0:
            total_batch = signal_latency + ingest_latency
            print(f"    Total end-to-end: {total_batch:.3f}s ({ingest_latency:.3f}s ingest + {signal_latency:.3f}s signal)")
        print(f"    → Acceptable even at higher latencies")
        print(f"    → Opportunity: Pre-cache features during off-hours")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Profile signal generation latency")
    parser.add_argument(
        "--fresh-ingest",
        action="store_true",
        help="Force fresh data ingestion from APIs (slower, shows full end-to-end)"
    )
    
    args = parser.parse_args()
    
    profiler = SignalLatencyProfiler(verbose=True)
    results = profiler.profile_signal_generation(fresh_ingest=args.fresh_ingest)
    
    profiler.print_analysis(results)
    
    # Save results
    output_file = Path("profiling") / f"signal_latency_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\nResults saved to {output_file}\n")


if __name__ == "__main__":
    main()
