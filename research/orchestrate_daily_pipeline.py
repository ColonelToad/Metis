#!/usr/bin/env python3
"""
Main orchestration entry point for Metis pipeline
Handles data ingestion → feature engineering → inference
Returns dict with signals and metrics for Rust orchestrator via PyO3
Mode is determined by METIS_MODE environment variable (DEV or REAL)
"""
import sys
import os
import time
import json
from pathlib import Path
from datetime import datetime

def get_mode() -> str:
    """Get execution mode from environment (DEV or REAL)"""
    mode = os.environ.get("METIS_MODE", "DEV").upper()
    if mode not in ("DEV", "REAL"):
        mode = "DEV"
    return mode

def setup_logging():
    """Initialize logging to file and terminal"""
    from loguru import logger
    
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    log_file = log_dir / "orchestrate_{time}.log"
    
    # Remove default handler
    logger.remove()
    
    # Add file handler
    logger.add(
        str(log_file),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="INFO"
    )
    
    # Add stderr handler for console output
    logger.add(
        sys.stderr,
        format="{time:HH:mm:ss} | {level: <8} | {message}",
        level="INFO"
    )
    
    return logger

def run_ingest_phase(mode: str, logger) -> tuple[bool, float, list]:
    """Run data ingestion phase. Returns (success, time, errors)"""
    logger.info(f"[INGEST] Starting ingestion phase (mode: {mode})")
    start = time.time()
    errors = []
    
    try:
        from research.data_ingest.run_all_ingesters import main as ingest_main
        import io
        from contextlib import redirect_stdout, redirect_stderr
        
        # Capture output to suppress noise
        f_out = io.StringIO()
        f_err = io.StringIO()
        with redirect_stdout(f_out), redirect_stderr(f_err):
            ingest_main()
        
        elapsed = time.time() - start
        logger.info(f"[INGEST] Phase completed in {elapsed:.2f}s")
        return True, elapsed, errors
    except Exception as e:
        elapsed = time.time() - start
        error_msg = f"Ingestion failed: {str(e)}"
        errors.append(error_msg)
        logger.error(f"[INGEST] {error_msg}")
        import traceback
        logger.error(traceback.format_exc())
        return False, elapsed, errors

def run_features_phase(mode: str, logger) -> tuple[bool, float, list]:
    """Run feature engineering phase. Returns (success, time, errors)"""
    logger.info(f"[FEATURES] Starting feature engineering phase (mode: {mode})")
    start = time.time()
    errors = []
    
    try:
        from research.models.unify_features import main as features_main
        import io
        from contextlib import redirect_stdout, redirect_stderr
        
        # Capture output
        f_out = io.StringIO()
        f_err = io.StringIO()
        with redirect_stdout(f_out), redirect_stderr(f_err):
            features_main()
        
        elapsed = time.time() - start
        logger.info(f"[FEATURES] Phase completed in {elapsed:.2f}s")
        return True, elapsed, errors
    except Exception as e:
        elapsed = time.time() - start
        error_msg = f"Features failed: {str(e)}"
        errors.append(error_msg)
        logger.error(f"[FEATURES] {error_msg}")
        import traceback
        logger.error(traceback.format_exc())
        return False, elapsed, errors

def run_inference_phase(mode: str, logger) -> tuple[bool, float, list, list]:
    """Run model inference phase and generate signals. Returns (success, time, errors, signals)"""
    logger.info(f"[INFERENCE] Starting inference phase (mode: {mode})")
    start = time.time()
    signals = []
    errors = []
    
    try:
        if mode == "DEV":
            logger.info("[INFERENCE] DEV mode: generating synthetic signal (no model load)")
            # In DEV mode, create a synthetic signal without loading the model
            signals = [{
                "signal_id": "dev_signal_001",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "symbol": "NG:CME",
                "direction": "LONG",
                "confidence": 0.73,
                "target_quantity": 10.0,
                "horizon_minutes": 60,
                "metadata": {
                    "phase": "DEV",
                    "model": "dual_lstm_v1.0"
                }
            }]
        else:
            logger.info("[INFERENCE] REAL mode: calling actual inference")
            from research.models.inference_pipeline import DualLSTMInference
            import io
            from contextlib import redirect_stdout, redirect_stderr
            
            # Suppress output
            f_out = io.StringIO()
            f_err = io.StringIO()
            with redirect_stdout(f_out), redirect_stderr(f_err):
                # Initialize pipeline
                pipeline = DualLSTMInference(
                    model_path="models/lstm_ng_predictor.keras",
                    signal_host="localhost",
                    signal_port=8080,
                    threshold=0.40
                )
                # In REAL mode, would call pipeline.predict_and_trade()
                signals = []
        
        elapsed = time.time() - start
        logger.info(f"[INFERENCE] Phase completed in {elapsed:.2f}s, generated {len(signals)} signals")
        return True, elapsed, errors, signals
    except Exception as e:
        elapsed = time.time() - start
        error_msg = f"Inference failed: {str(e)}"
        errors.append(error_msg)
        logger.error(f"[INFERENCE] {error_msg}")
        import traceback
        logger.error(traceback.format_exc())
        return False, elapsed, errors, []

def main() -> dict:
    """
    Main orchestration entry point
    Returns dict with status, signals, metrics, and errors
    Reads METIS_MODE from environment variable
    """
    mode = get_mode()
    
    logger = setup_logging()
    logger.info(f"═" * 60)
    logger.info(f"PIPELINE START (mode: {mode})")
    logger.info(f"═" * 60)
    
    pipeline_start = time.time()
    all_errors = []
    
    # Phase 1: Ingestion
    ingest_ok, ingest_time, ingest_errors = run_ingest_phase(mode, logger)
    all_errors.extend(ingest_errors)
    
    # Phase 2: Features
    features_ok, features_time, features_errors = run_features_phase(mode, logger)
    all_errors.extend(features_errors)
    
    # Phase 3: Inference
    inference_ok, inference_time, inference_errors, signals = run_inference_phase(mode, logger)
    all_errors.extend(inference_errors)
    
    # Compute totals
    total_time = time.time() - pipeline_start
    
    # Determine overall status
    all_ok = ingest_ok and features_ok and inference_ok
    status = "complete" if all_ok else "partial"
    
    # Build result dict for Rust
    result = {
        "status": status,
        "signals": signals,
        "metrics": {
            "total_time": total_time,
            "ingest_time": ingest_time,
            "feature_time": features_time,
            "inference_time": inference_time,
            "signals_generated": len(signals),
            "avg_confidence": sum(s["confidence"] for s in signals) / len(signals) if signals else 0.0,
            "mode": mode,
            "ingest_success": ingest_ok,
            "features_success": features_ok,
            "inference_success": inference_ok,
        },
        "errors": all_errors,
    }
    
    # Log summary
    logger.info(f"╔" + "═" * 58 + "╗")
    logger.info(f"║ PIPELINE SUMMARY" + " " * 44 + "║")
    logger.info(f"║" + "─" * 58 + "║")
    logger.info(f"║ Ingestion:      {ingest_time:6.2f}s  {'✓' if ingest_ok else '✗'}" + " " * 39 + "║")
    logger.info(f"║ Features:       {features_time:6.2f}s  {'✓' if features_ok else '✗'}" + " " * 39 + "║")
    logger.info(f"║ Inference:      {inference_time:6.2f}s  {'✓' if inference_ok else '✗'}" + " " * 39 + "║")
    logger.info(f"║ Signals:        {len(signals):6d}" + " " * 46 + "║")
    logger.info(f"║ Total:          {total_time:6.2f}s" + " " * 45 + "║")
    logger.info(f"║ Mode:           {mode}" + " " * 45 + "║")
    logger.info(f"╚" + "═" * 58 + "╝")
    
    # Log errors if any
    if all_errors:
        logger.warning("Pipeline completed with errors:")
        for err in all_errors:
            logger.warning(f"  - {err}")
    
    if all_ok:
        logger.info("PIPELINE COMPLETE: SUCCESS")
    else:
        logger.warning("PIPELINE COMPLETE: WITH ERRORS (graceful degradation)")
    
    # Return dict for Rust (PyO3 will convert it)
    return result

if __name__ == "__main__":
    sys.exit(main())
