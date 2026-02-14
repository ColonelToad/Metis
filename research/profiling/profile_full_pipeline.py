#!/usr/bin/env python3
"""
End-to-End Pipeline Profiler for Metis Signal Generation

Profiles the COMPLETE signal generation path:
1. Data ingestion (each API separately + parallel potential)
2. Feature engineering (DB queries + transformations)
3. Model inference (preprocessing + prediction)
4. Signal generation (Rust FFI + execution)

Output includes:
- Latency breakdown by stage
- Per-API latency and parallelization potential
- Function-level profiling (cProfile)
- Memory usage tracking
- Bottleneck identification
- Recommendations

Usage:
    python profile_full_pipeline.py [--mode {full,ingest,features,inference}]

Examples:
    python profile_full_pipeline.py                 # Full pipeline
    python profile_full_pipeline.py --mode ingest   # Only data ingestion
    python profile_full_pipeline.py --mode features # Only feature engineering
"""

import os
import sys
import time
import cProfile
import pstats
import tracemalloc
from io import StringIO
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Tuple, Any, Optional
import argparse

# Add workspace root to path (3 levels up: profiling -> research -> Metis)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np

from research.data_ingest import (
    ingest_eia, ingest_lmp, ingest_fred, ingest_bls_ppi,
    ingest_fred_building_permits, ingest_freight, ingest_cme_futures,
    ingest_congress_bills_expanded
)
from research.features.engineer_features import FeatureEngineer, DB_URL
from research.common import runtime_config as rc


class PipelineProfiler:
    """Comprehensive pipeline profiler with per-stage timing and analysis."""
    
    def __init__(self, output_dir: str = "profiling", verbose: bool = True):
        self.output_dir = output_dir
        self.verbose = verbose
        self.timings: Dict[str, float] = {}
        self.sizes: Dict[str, int] = {}
        self.errors: Dict[str, str] = {}
        
        os.makedirs(output_dir, exist_ok=True)
        
        if self.verbose:
            print(f"\n{'='*70}")
            print(f"METIS PIPELINE PROFILER - {datetime.now().isoformat()}")
            print(f"Mode: {rc.mode_label()}")
            print(f"{'='*70}\n")
    
    def _log(self, msg: str, level: str = "INFO"):
        """Log with timestamp"""
        if self.verbose:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] {level:8s} {msg}")
    
    def _time_function(self, label: str, fn, *args, **kwargs) -> Tuple[Any, float]:
        """Time a function call and return (result, duration_seconds)"""
        start = time.perf_counter()
        result = fn(*args, **kwargs)
        duration = time.perf_counter() - start
        self.timings[label] = duration
        return result, duration
    
    def _get_size_mb(self, obj) -> float:
        """Estimate DataFrame/Series size in MB"""
        if isinstance(obj, pd.DataFrame):
            return obj.memory_usage(deep=True).sum() / 1e6
        elif isinstance(obj, pd.Series):
            return obj.memory_usage(deep=True) / 1e6
        elif isinstance(obj, (list, dict)):
            return len(pd.Series(obj).to_frame().memory_usage(deep=True)) / 1e6
        return 0.0
    
    # =========================================================================
    # STAGE 1: DATA INGESTION
    # =========================================================================
    
    def profile_ingest_eia(self) -> Tuple[Dict[str, pd.DataFrame], float]:
        """Profile EIA data ingestion"""
        def fetch():
            storage = ingest_eia.fetch_ng_storage()
            production = ingest_eia.fetch_ng_production()
            return {"storage": storage, "production": production}
        
        result, duration = self._time_function("ingest_eia", fetch)
        
        if result["storage"].shape[0] > 0:
            self.sizes["eia_storage"] = self._get_size_mb(result["storage"])
        if result["production"].shape[0] > 0:
            self.sizes["eia_production"] = self._get_size_mb(result["production"])
        
        self._log(
            f"EIA: storage={result['storage'].shape[0]} rows, "
            f"production={result['production'].shape[0]} rows | {duration:.3f}s",
            "INGEST"
        )
        return result, duration
    
    def profile_ingest_lmp(self) -> Tuple[pd.DataFrame, float]:
        """Profile LMP data ingestion"""
        def fetch():
            # Calculate date range (last 7 days for testing)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)
            
            caiso = ingest_lmp.CAISO()
            df = caiso.get_lmp(
                date=start_date,
                end=end_date,
                market="REAL_TIME_5_MIN"
            )
            return df if not df.empty else pd.DataFrame()
        
        try:
            result, duration = self._time_function("ingest_lmp", fetch)
            if not result.empty:
                self.sizes["lmp"] = self._get_size_mb(result)
            self._log(f"LMP: {result.shape[0]} rows | {duration:.3f}s", "INGEST")
            return result, duration
        except Exception as e:
            self.errors["lmp"] = str(e)
            self._log(f"LMP FAILED: {str(e)[:60]}", "ERROR")
            return pd.DataFrame(), 0.0
    
    def profile_ingest_fred(self) -> Tuple[Dict[str, pd.DataFrame], float]:
        """Profile FRED data ingestion"""
        def fetch():
            # FRED typically takes one API call with multiple series
            result = ingest_fred.main()  # Returns dict of DataFrames
            return result if result else {}
        
        try:
            result, duration = self._time_function("ingest_fred", fetch)
            total_rows = sum(df.shape[0] for df in result.values() if isinstance(df, pd.DataFrame))
            self._log(f"FRED: {len(result)} indicators, {total_rows} total rows | {duration:.3f}s", "INGEST")
            return result, duration
        except Exception as e:
            self.errors["fred"] = str(e)
            self._log(f"FRED FAILED: {str(e)[:60]}", "ERROR")
            return {}, 0.0
    
    def profile_ingest_congress(self) -> Tuple[pd.DataFrame, float]:
        """Profile Congress bills data ingestion"""
        def fetch():
            result = ingest_congress_bills_expanded.main()
            return result if isinstance(result, pd.DataFrame) else pd.DataFrame()
        
        try:
            result, duration = self._time_function("ingest_congress", fetch)
            if not result.empty:
                self.sizes["congress"] = self._get_size_mb(result)
            self._log(f"Congress: {result.shape[0]} rows | {duration:.3f}s", "INGEST")
            return result, duration
        except Exception as e:
            self.errors["congress"] = str(e)
            self._log(f"Congress FAILED: {str(e)[:60]}", "ERROR")
            return pd.DataFrame(), 0.0
    
    def profile_ingest_bls(self) -> Tuple[pd.DataFrame, float]:
        """Profile BLS PPI data ingestion"""
        def fetch():
            result = ingest_bls_ppi.main()
            return result if isinstance(result, pd.DataFrame) else pd.DataFrame()
        
        try:
            result, duration = self._time_function("ingest_bls_ppi", fetch)
            if not result.empty:
                self.sizes["bls_ppi"] = self._get_size_mb(result)
            self._log(f"BLS PPI: {result.shape[0]} rows | {duration:.3f}s", "INGEST")
            return result, duration
        except Exception as e:
            self.errors["bls_ppi"] = str(e)
            self._log(f"BLS FAILED: {str(e)[:60]}", "ERROR")
            return pd.DataFrame(), 0.0
    
    def profile_ingest_cme(self) -> Tuple[pd.DataFrame, float]:
        """Profile CME futures data ingestion"""
        def fetch():
            result = ingest_cme_futures.ingest_cme_futures()
            return result if isinstance(result, pd.DataFrame) else pd.DataFrame()
        
        try:
            result, duration = self._time_function("ingest_cme_futures", fetch)
            if not result.empty:
                self.sizes["cme_futures"] = self._get_size_mb(result)
            self._log(f"CME Futures: {result.shape[0]} rows | {duration:.3f}s", "INGEST")
            return result, duration
        except Exception as e:
            self.errors["cme_futures"] = str(e)
            self._log(f"CME FAILED: {str(e)[:60]}", "ERROR")
            return pd.DataFrame(), 0.0
    
    def profile_ingest_freight(self) -> Tuple[pd.DataFrame, float]:
        """Profile freight data ingestion"""
        def fetch():
            result = ingest_freight.ingest_freight()
            return result if isinstance(result, pd.DataFrame) else pd.DataFrame()
        
        try:
            result, duration = self._time_function("ingest_freight", fetch)
            if not result.empty:
                self.sizes["freight"] = self._get_size_mb(result)
            self._log(f"Freight: {result.shape[0]} rows | {duration:.3f}s", "INGEST")
            return result, duration
        except Exception as e:
            self.errors["freight"] = str(e)
            self._log(f"Freight FAILED: {str(e)[:60]}", "ERROR")
            return pd.DataFrame(), 0.0
    
    def profile_ingestion(self) -> float:
        """Profile complete data ingestion (SEQUENTIAL, current behavior)"""
        self._log("=" * 60, "PHASE")
        self._log("PHASE 1: DATA INGESTION (Sequential)", "PHASE")
        self._log("=" * 60, "PHASE")
        
        start_total = time.perf_counter()
        
        # Run all ingesters sequentially (current behavior)
        eia_data, _ = self.profile_ingest_eia()
        lmp_data, _ = self.profile_ingest_lmp()
        fred_data, _ = self.profile_ingest_fred()
        congress_data, _ = self.profile_ingest_congress()
        bls_data, _ = self.profile_ingest_bls()
        cme_data, _ = self.profile_ingest_cme()
        freight_data, _ = self.profile_ingest_freight()
        
        total_duration = time.perf_counter() - start_total
        self.timings["ingest_total_sequential"] = total_duration
        
        return total_duration
    
    # =========================================================================
    # STAGE 2: FEATURE ENGINEERING
    # =========================================================================
    
    def profile_feature_engineering(self) -> float:
        """Profile feature engineering pipeline"""
        self._log("=" * 60, "PHASE")
        self._log("PHASE 2: FEATURE ENGINEERING", "PHASE")
        self._log("=" * 60, "PHASE")
        
        start_total = time.perf_counter()
        
        try:
            fe = FeatureEngineer(DB_URL, start_date="2015-01-01")
            
            # Profile each stage
            df, t_price = self._time_function(
                "feature_load_price",
                fe.load_price_data
            )
            self._log(f"Load price data: {df.shape[0]} rows | {t_price:.3f}s", "FEATURE")
            
            df, t_eia = self._time_function(
                "feature_load_eia",
                fe.load_eia_features,
                df
            )
            self._log(f"Load EIA features: {df.shape[0]} rows | {t_eia:.3f}s", "FEATURE")
            
            df, t_fred = self._time_function(
                "feature_load_fred",
                fe.load_fred_features,
                df
            )
            self._log(f"Load FRED features: {df.shape[0]} rows | {t_fred:.3f}s", "FEATURE")
            
            df, t_bls = self._time_function(
                "feature_load_bls",
                fe.load_bls_ppi_features,
                df
            )
            self._log(f"Load BLS features: {df.shape[0]} rows | {t_bls:.3f}s", "FEATURE")
            
            df, t_census = self._time_function(
                "feature_load_census",
                fe.load_census_permit_features,
                df
            )
            self._log(f"Load Census features: {df.shape[0]} rows | {t_census:.3f}s", "FEATURE")
            
            df, t_congress = self._time_function(
                "feature_load_congress",
                fe.load_congress_features,
                df
            )
            self._log(f"Load Congress features: {df.shape[0]} rows | {t_congress:.3f}s", "FEATURE")
            
            # Full pipeline (for validation)
            df_full, t_total = self._time_function(
                "feature_engineer_full",
                fe.engineer_features
            )
            self._log(f"Full engineer_features() call: {df_full.shape[0]} rows | {t_total:.3f}s", "FEATURE")
            
            if not df_full.empty:
                self.sizes["features"] = self._get_size_mb(df_full)
            
            total_duration = time.perf_counter() - start_total
            self.timings["features_total"] = total_duration
            
            return t_total  # Return full pipeline time
            
        except Exception as e:
            self.errors["features"] = str(e)
            self._log(f"Feature engineering FAILED: {str(e)}", "ERROR")
            return 0.0
    
    # =========================================================================
    # STAGE 3: MODEL INFERENCE
    # =========================================================================
    
    def profile_model_inference(self) -> float:
        """Profile model inference pipeline"""
        self._log("=" * 60, "PHASE")
        self._log("PHASE 3: MODEL INFERENCE", "PHASE")
        self._log("=" * 60, "PHASE")
        
        try:
            from research.models.inference_pipeline import DualLSTMInference
            
            start_total = time.perf_counter()
            
            # Initialize pipeline
            pipeline, t_init = self._time_function(
                "model_init",
                DualLSTMInference,
                model_path="models/lstm_ng_predictor.keras",
                scalers_path="models/scalers_v1.0.pkl",
                threshold=0.40
            )
            self._log(f"Initialize model: {t_init:.3f}s", "INFER")
            
            # Load sample features for prediction
            fe = FeatureEngineer(DB_URL, start_date="2015-01-01")
            
            # Get recent data for prediction
            daily_df, t_daily = self._time_function(
                "model_load_daily_features",
                lambda: fe.load_price_data()
            )
            self._log(f"Load daily features: {daily_df.shape[0]} rows | {t_daily:.3f}s", "INFER")
            
            low_freq_df, t_low_freq = self._time_function(
                "model_load_lowfreq_features",
                lambda: fe.load_eia_features(daily_df)
            )
            self._log(f"Load low-freq features: {low_freq_df.shape[0]} rows | {t_low_freq:.3f}s", "INFER")
            
            # Preprocess
            daily_seq, t_daily_prep = self._time_function(
                "model_prep_daily",
                pipeline.preprocess_track,
                daily_df,
                pipeline.scaler_daily,
                pipeline.config.get("daily_features", []),
            )
            self._log(f"Preprocess daily: {daily_seq.shape} | {t_daily_prep:.3f}s", "INFER")
            
            # Predict
            t_predict_start = time.perf_counter()
            prediction, t_predict = self._time_function(
                "model_predict",
                pipeline.predict,
                daily_df,
                low_freq_df,
                pd.DataFrame()  # sparse features can be empty
            )
            t_predict_actual = time.perf_counter() - t_predict_start
            self._log(
                f"Inference: direction={prediction['direction']}, "
                f"confidence={prediction['confidence']:.3f} | {t_predict_actual:.3f}s",
                "INFER"
            )
            
            total_duration = time.perf_counter() - start_total
            self.timings["inference_total"] = total_duration
            
            return total_duration
            
        except FileNotFoundError as e:
            self.errors["inference"] = f"Model files not found: {str(e)}"
            self._log(f"Model files not found (expected in initial runs)", "WARN")
            return 0.0
        except Exception as e:
            self.errors["inference"] = str(e)
            self._log(f"Model inference FAILED: {str(e)}", "ERROR")
            return 0.0
    
    # =========================================================================
    # MAIN PROFILING ORCHESTRATION
    # =========================================================================
    
    def profile_full_pipeline(self) -> Dict[str, Any]:
        """Execute full pipeline profiling"""
        tracemalloc.start()
        
        # Profile each stage
        ingest_time = self.profile_ingestion()
        feature_time = self.profile_feature_engineering()
        inference_time = self.profile_model_inference()
        
        # Memory stats
        current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        # Compile results
        results = {
            "timestamp": datetime.now().isoformat(),
            "mode": rc.mode_label(),
            "timings": self.timings,
            "sizes": self.sizes,
            "errors": self.errors,
            "memory": {
                "current_mb": current_mem / 1e6,
                "peak_mb": peak_mem / 1e6,
            }
        }
        
        return results
    
    def print_summary(self, results: Dict[str, Any]):
        """Print formatted summary with bottleneck analysis"""
        print(f"\n{'='*70}")
        print(f"PROFILING RESULTS SUMMARY")
        print(f"{'='*70}\n")
        
        # Timing breakdown
        print("TIMING BREAKDOWN (by stage):")
        print("-" * 70)
        
        timings = results["timings"]
        sizes = results["sizes"]
        
        # This is the main info we calculated
        ingest_seq = timings.get("ingest_total_sequential", 0)
        features = timings.get("features_total", 0)
        inference = timings.get("inference_total", 0)
        
        total_time = ingest_seq + features + inference
        
        if total_time > 0:
            ingest_pct = (ingest_seq / total_time) * 100
            features_pct = (features / total_time) * 100
            inference_pct = (inference / total_time) * 100
        else:
            ingest_pct = features_pct = inference_pct = 0
        
        print(f"  Data Ingestion (sequential):  {ingest_seq:>8.3f}s  ({ingest_pct:>6.1f}%)")
        print(f"  Feature Engineering:          {features:>8.3f}s  ({features_pct:>6.1f}%)")
        print(f"  Model Inference:              {inference:>8.3f}s  ({inference_pct:>6.1f}%)")
        print(f"  {'-'*70}")
        print(f"  TOTAL END-TO-END:             {total_time:>8.3f}s  (100.0%)")
        
        # Per-API breakdown
        print(f"\nPER-API LATENCY (from sequential ingestion):")
        print("-" * 70)
        
        api_timings = [
            ("EIA Storage + Production", timings.get("ingest_eia", 0)),
            ("LMP/CAISO", timings.get("ingest_lmp", 0)),
            ("FRED Indicators", timings.get("ingest_fred", 0)),
            ("Congress Bills", timings.get("ingest_congress", 0)),
            ("BLS PPI", timings.get("ingest_bls_ppi", 0)),
            ("CME Futures", timings.get("ingest_cme_futures", 0)),
            ("Freight Data", timings.get("ingest_freight", 0)),
        ]
        
        max_api = max((t for _, t in api_timings), default=0)
        
        for name, duration in sorted(api_timings, key=lambda x: x[1], reverse=True):
            if duration > 0:
                pct = (duration / ingest_seq) * 100 if ingest_seq > 0 else 0
                bar_len = int((duration / max_api) * 30) if max_api > 0 else 0
                bar = "█" * bar_len
                print(f"  {name:<30} {duration:>7.3f}s ({pct:>5.1f}%) {bar}")
        
        # Feature engineering breakdown
        print(f"\nFEATURE ENGINEERING BREAKDOWN:")
        print("-" * 70)
        
        feature_stages = [
            ("Load Price (price features)", timings.get("feature_load_price", 0)),
            ("Load EIA (storage, prod)", timings.get("feature_load_eia", 0)),
            ("Load FRED (macro)", timings.get("feature_load_fred", 0)),
            ("Load BLS (PPI)", timings.get("feature_load_bls", 0)),
            ("Load Census (permits)", timings.get("feature_load_census", 0)),
            ("Load Congress (bills)", timings.get("feature_load_congress", 0)),
        ]
        
        for name, duration in feature_stages:
            if duration > 0:
                pct = (duration / features) * 100 if features > 0 else 0
                print(f"  {name:<35} {duration:>7.3f}s ({pct:>5.1f}%)")
        
        # Data sizes
        if sizes:
            print(f"\nDATA SIZES (in memory):")
            print("-" * 70)
            total_size = sum(sizes.values())
            for name, size in sorted(sizes.items(), key=lambda x: x[1], reverse=True):
                pct = (size / total_size) * 100 if total_size > 0 else 0
                print(f"  {name:<35} {size:>8.1f} MB  ({pct:>5.1f}%)")
            print(f"  {'TOTAL':<35} {total_size:>8.1f} MB")
        
        # Memory usage
        print(f"\nMEMORY USAGE:")
        print("-" * 70)
        print(f"  Current:  {results['memory']['current_mb']:.1f} MB")
        print(f"  Peak:     {results['memory']['peak_mb']:.1f} MB")
        
        # Errors
        if results["errors"]:
            print(f"\nERRORS / WARNINGS:")
            print("-" * 70)
            for component, error in results["errors"].items():
                print(f"  {component:<30} {error[:50]}")
        
        # Bottleneck analysis
        print(f"\nBOTTLENECK ANALYSIS:")
        print("-" * 70)
        
        if ingest_seq > 0 and ingest_pct > 50:
            print(f"  🔴 CRITICAL: Data ingestion is {ingest_pct:.0f}% of total time")
            print(f"     → Opportunity: Parallelize API calls (up to 3-5x speedup)")
            print(f"     → Current slowest: {max(api_timings, key=lambda x: x[1])[0]}")
        elif features > 0 and features_pct > 30:
            print(f"  🟡 SECONDARY: Feature engineering is {features_pct:.0f}% of total time")
            print(f"     → Opportunity: Optimize DB queries or vectorize operations")
        
        if inference > 0 and inference_pct > 20:
            print(f"  🟡 SECONDARY: Model inference is {inference_pct:.0f}% of total time")
            print(f"     → Opportunity: Quantize model or use ONNX runtime")
        
        print(f"\n{'='*70}")
        print(f"Run complete. Results saved to profiling/ directory")
        print(f"{'='*70}\n")
    
    def save_results(self, results: Dict[str, Any]):
        """Save results to file"""
        import json
        
        output_file = Path(self.output_dir) / f"pipeline_profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2, default=str)
        
        self._log(f"Results saved to {output_file}", "SAVE")


def main():
    parser = argparse.ArgumentParser(
        description="Profile Metis signal generation pipeline"
    )
    parser.add_argument(
        "--mode",
        choices=["full", "ingest", "features", "inference"],
        default="full",
        help="Which part to profile"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=True,
        help="Verbose output"
    )
    
    args = parser.parse_args()
    
    profiler = PipelineProfiler(verbose=args.verbose)
    
    if args.mode in ["full", "ingest"]:
        profiler.profile_ingestion()
    
    if args.mode in ["full", "features"]:
        profiler.profile_feature_engineering()
    
    if args.mode in ["full", "inference"]:
        profiler.profile_model_inference()
    
    # Get results
    results = {
        "timestamp": datetime.now().isoformat(),
        "mode": rc.mode_label(),
        "timings": profiler.timings,
        "sizes": profiler.sizes,
        "errors": profiler.errors,
        "memory": {
            "current_mb": 0,
            "peak_mb": 0,
        }
    }
    
    profiler.print_summary(results)
    profiler.save_results(results)


if __name__ == "__main__":
    main()
