"""
Dual LSTM + Fusion Model Inference Pipeline
============================================

Production-ready module for generating trading signals from the dual LSTM model.
Interfaces with Rust execution engine via SignalClient.

Usage:
    from inference_pipeline import DualLSTMInference
    
    pipeline = DualLSTMInference(model_path="models/dual_lstm_v1.0.h5")
    signal = pipeline.predict(daily_features, low_freq_features, sparse_features)
    pipeline.send_to_execution(signal)
"""

import os
import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, Tuple, Optional, Any
import uuid
import pickle

import tensorflow as tf
from sklearn.preprocessing import StandardScaler

from signal_client import SignalClient, create_signal
from loguru import logger


class DualLSTMInference:
    """
    Production inference engine for Dual LSTM + Fusion model.
    
    Loads pre-trained model and scalers, generates predictions,
    and sends signals to Rust execution engine.
    """
    
    def __init__(
        self,
        model_path: str = "models/dual_lstm_v1.0.h5",
        scalers_path: str = "models/scalers_v1.0.pkl",
        config_path: str = "config/model_config.yaml",
        signal_host: str = "localhost",
        signal_port: int = 8080,
        threshold: float = 0.40,
    ):
        """
        Initialize inference pipeline.
        
        Args:
            model_path: Path to trained TensorFlow model (h5 format)
            scalers_path: Path to pickled scalers (daily, low_freq, sparse)
            config_path: Path to model configuration YAML
            signal_host: Rust execution engine host
            signal_port: Rust execution engine port
            threshold: Classification threshold for buy signals (default: 0.40)
        """
        self.model_path = model_path
        self.scalers_path = scalers_path
        self.config_path = config_path
        self.threshold = threshold
        
        # Load model
        logger.info(f"Loading model from {model_path}")
        self.model = tf.keras.models.load_model(model_path)
        
        # Load scalers
        logger.info(f"Loading scalers from {scalers_path}")
        with open(scalers_path, "rb") as f:
            self.scaler_daily, self.scaler_low_freq, self.scaler_sparse = pickle.load(f)
        
        # Load config
        logger.info(f"Loading config from {config_path}")
        with open(config_path) as f:
            import yaml
            self.config = yaml.safe_load(f)
        
        # Initialize signal client (lazy connection on first send)
        self.signal_client = SignalClient(host=signal_host, port=signal_port)
        self.connected = False
        
        logger.info(f"DualLSTM pipeline initialized (threshold={threshold})")
    
    def preprocess_track(
        self,
        df: pd.DataFrame,
        scaler: StandardScaler,
        feature_cols: list,
        lookback: int = 20,
    ) -> np.ndarray:
        """
        Preprocess a single frequency track into sequences.
        
        Args:
            df: DataFrame with raw features
            scaler: StandardScaler fitted on training data
            feature_cols: List of column names to use
            lookback: Sequence length (default 20 days)
        
        Returns:
            Sequences array of shape (1, lookback, num_features)
        """
        # Get last `lookback` rows
        if len(df) < lookback:
            raise ValueError(
                f"Not enough data. Got {len(df)} rows, need ≥{lookback}"
            )
        
        recent_data = df[feature_cols].iloc[-lookback:].values
        
        # Scale using pre-fitted scaler
        scaled_data = scaler.transform(recent_data)
        
        # Return as sequence (add batch dimension)
        return np.expand_dims(scaled_data, axis=0)  # Shape: (1, 20, num_features)
    
    def predict(
        self,
        daily_df: pd.DataFrame,
        low_freq_df: pd.DataFrame,
        sparse_df: pd.DataFrame,
    ) -> Dict[str, Any]:
        """
        Generate prediction from model.
        
        Args:
            daily_df: Daily features dataframe (must have date index)
            low_freq_df: Low-frequency features dataframe
            sparse_df: Sparse event features dataframe
        
        Returns:
            Dictionary with prediction details:
                {
                    'probability': float 0.0-1.0,
                    'direction': 'Long' | 'Short' | 'Neutral',
                    'confidence': float 0.0-1.0,
                    'timestamp': str ISO format,
                    'lookback_end_date': str,
                }
        """
        logger.info("Generating prediction...")
        
        # Get feature column names from config
        daily_cols = self.config["daily_features"]
        low_freq_cols = self.config["low_freq_features"]
        sparse_cols = self.config["sparse_features"]
        lookback = self.config.get("lookback", 20)
        
        # Preprocess each track
        X_daily = self.preprocess_track(daily_df, self.scaler_daily, daily_cols, lookback)
        X_low_freq = self.preprocess_track(low_freq_df, self.scaler_low_freq, low_freq_cols, lookback)
        X_sparse = self.preprocess_track(sparse_df, self.scaler_sparse, sparse_cols, lookback)
        
        # Forward pass
        prob = self.model.predict(
            [X_daily, X_low_freq, X_sparse],
            verbose=0
        )[0][0]  # Shape: (1, 1) -> scalar
        
        # Determine direction
        if prob > self.threshold:
            direction = "Long"
            confidence = float(prob)
        else:
            direction = "Neutral"
            confidence = 1.0 - float(prob)  # Confidence in down direction
        
        result = {
            "probability": float(prob),
            "direction": direction,
            "confidence": confidence,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "lookback_end_date": str(daily_df.index[-1].date()) if hasattr(daily_df.index[-1], 'date') else str(daily_df.iloc[-1, 0]),
        }
        
        logger.info(
            f"Prediction: {direction} @ {prob:.1%} confidence "
            f"(threshold={self.threshold:.2f})"
        )
        
        return result
    
    def prediction_to_signal(
        self,
        prediction: Dict[str, Any],
        symbol: str = "NG:CME",
        target_quantity: float = 10.0,
        horizon_minutes: int = 60,
    ) -> Dict[str, Any]:
        """
        Convert model prediction to trading signal format.
        
        Args:
            prediction: Output from predict()
            symbol: Trading instrument
            target_quantity: Number of contracts
            horizon_minutes: Time window for execution
        
        Returns:
            Signal dictionary ready for execution engine
        """
        signal = create_signal(
            signal_id=str(uuid.uuid4()),
            symbol=symbol,
            direction=prediction["direction"],
            confidence=prediction["confidence"],
            target_quantity=target_quantity,
            horizon_minutes=horizon_minutes,
            model_version=self.config.get("version", "v1.0"),
            features_used=self.config.get("daily_features", [])
                          + self.config.get("low_freq_features", [])
                          + self.config.get("sparse_features", []),
        )
        
        logger.info(f"Signal created: {signal['signal_id']}")
        return signal
    
    def send_to_execution(
        self,
        signal: Dict[str, Any],
        connect: bool = True,
        disconnect_after: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Send signal to Rust execution engine.
        
        Args:
            signal: Output from prediction_to_signal()
            connect: Auto-connect if not already connected
            disconnect_after: Close connection after send
        
        Returns:
            Execution response or None on error
        """
        # Connect if needed
        if not self.connected and connect:
            if not self.signal_client.connect():
                logger.error("Failed to connect to execution engine")
                return None
            self.connected = True
        
        # Send
        response = self.signal_client.send_signal(signal)
        
        # Disconnect if requested
        if disconnect_after:
            self.signal_client.disconnect()
            self.connected = False
        
        if response:
            logger.info(f"Execution response: {response['status']}")
        
        return response
    
    def predict_and_trade(
        self,
        daily_df: pd.DataFrame,
        low_freq_df: pd.DataFrame,
        sparse_df: pd.DataFrame,
        symbol: str = "NG:CME",
        target_quantity: float = 10.0,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        End-to-end: predict → convert → send to execution.
        
        Args:
            daily_df: Daily features
            low_freq_df: Low-frequency features
            sparse_df: Sparse features
            symbol: Trading symbol
            target_quantity: Contracts to trade
            dry_run: If True, don't actually send signal
        
        Returns:
            Combined result with prediction and execution response
        """
        logger.info("="*70)
        logger.info("END-TO-END INFERENCE PIPELINE")
        logger.info("="*70)
        
        # Step 1: Predict
        prediction = self.predict(daily_df, low_freq_df, sparse_df)
        
        # Step 2: Convert to signal
        signal = self.prediction_to_signal(
            prediction,
            symbol=symbol,
            target_quantity=target_quantity,
        )
        
        # Step 3: Send (or dry run)
        execution_response = None
        if not dry_run:
            execution_response = self.send_to_execution(signal, connect=True)
        else:
            logger.info("[DRY RUN] Signal NOT sent to execution engine")
            logger.info(f"Would send: {signal}")
        
        result = {
            "prediction": prediction,
            "signal": signal,
            "execution_response": execution_response,
            "dry_run": dry_run,
        }
        
        logger.info("="*70)
        return result


def load_daily_data(csv_path: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Load feature dataframes from parquet files.
    
    Assumes standard structure:
        data/features/
        ├── test_daily_features.parquet
        ├── test_low_freq_features.parquet
        └── test_sparse_features.parquet
    
    Args:
        csv_path: Base path to data/features directory
    
    Returns:
        Tuple of (daily_df, low_freq_df, sparse_df)
    """
    base = Path(csv_path)
    
    daily_df = pd.read_parquet(base / "test_daily_features.parquet")
    low_freq_df = pd.read_parquet(base / "test_low_freq_features.parquet")
    sparse_df = pd.read_parquet(base / "test_sparse_features.parquet")
    
    # Ensure date column and set as index if exists
    for df in [daily_df, low_freq_df, sparse_df]:
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df.set_index("date", inplace=True)
    
    return daily_df, low_freq_df, sparse_df


if __name__ == "__main__":
    import sys
    
    # Example: Run inference on test set
    logger.info("Dual LSTM + Fusion Model - Inference Pipeline")
    logger.info("=" * 70)
    
    # Initialize pipeline
    pipeline = DualLSTMInference(
        model_path="models/dual_lstm_v1.0.h5",
        scalers_path="models/scalers_v1.0.pkl",
        config_path="config/model_config.yaml",
    )
    
    # Load test data
    daily_df, low_freq_df, sparse_df = load_daily_data("data/features")
    
    # Generate prediction
    result = pipeline.predict_and_trade(
        daily_df,
        low_freq_df,
        sparse_df,
        target_quantity=10.0,
        dry_run=False,  # Set to True to skip execution engine send
    )
    
    logger.info(f"\nPrediction: {result['prediction']}")
    logger.info(f"Signal ID: {result['signal']['signal_id']}")
    if result["execution_response"]:
        logger.info(f"Execution: {result['execution_response']['status']}")
