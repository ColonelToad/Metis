"""
Basic backtest harness for NG futures signals.
- Loads features CSV (train/val/test/all)
- Builds positions from a signal column (defaults to model predictions if present, else momentum_20d)
- Applies turnover-based transaction costs
- Reports Sharpe ratio, max drawdown, CAGR, total return
"""

import argparse
import os
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

DEFAULT_FEATURE_DIR = "data/features"
SPLIT_TO_FILE = {
    "all": os.path.join(DEFAULT_FEATURE_DIR, "all_features.csv"),
    "train": os.path.join(DEFAULT_FEATURE_DIR, "train_features.csv"),
    "val": os.path.join(DEFAULT_FEATURE_DIR, "val_features.csv"),
    "test": os.path.join(DEFAULT_FEATURE_DIR, "test_features.csv"),
}


@dataclass
class BacktestConfig:
    split: str = "test"
    signal_column: Optional[str] = "predicted_return"
    threshold: float = 0.0
    cost_per_turnover: float = 0.0005  # 5bps per side
    output_equity: Optional[str] = None


def load_features(split: str) -> pd.DataFrame:
    if split not in SPLIT_TO_FILE:
        raise ValueError(f"Unknown split '{split}'. Choose from {list(SPLIT_TO_FILE)}")
    path = SPLIT_TO_FILE[split]
    if not os.path.exists(path):
        raise FileNotFoundError(f"Features file not found: {path}")
    df = pd.read_csv(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def build_positions(df: pd.DataFrame, signal_column: Optional[str], threshold: float) -> pd.Series:
    usable_signal = None
    if signal_column and signal_column in df.columns:
        usable_signal = df[signal_column]
    elif "momentum_20d" in df.columns:
        usable_signal = df["momentum_20d"]
        print("[BACKTEST] Using momentum_20d as fallback signal")
    else:
        raise ValueError("No signal column found and no momentum_20d fallback available")

    usable_signal = pd.to_numeric(usable_signal, errors="coerce").fillna(0.0)
    positions = np.where(usable_signal > threshold, 1, np.where(usable_signal < -threshold, -1, 0))
    return pd.Series(positions, index=df.index, name="position")


def run_backtest(df: pd.DataFrame, positions: pd.Series, cost_per_turnover: float) -> pd.DataFrame:
    if "close" not in df.columns:
        raise ValueError("Input dataframe must include 'close' prices")

    returns = df["close"].pct_change().fillna(0.0)
    pos_shifted = positions.shift(1).fillna(0.0)
    gross = pos_shifted * returns

    turnover = positions.diff().abs().fillna(0.0)
    costs = turnover * cost_per_turnover
    net = gross - costs

    equity = (1 + net).cumprod()
    drawdown = equity / equity.cummax() - 1

    result = pd.DataFrame({
        "date": df.get("date"),
        "close": df["close"],
        "position": positions,
        "gross_return": gross,
        "cost": costs,
        "net_return": net,
        "equity": equity,
        "drawdown": drawdown,
    })
    return result


def summarize(result: pd.DataFrame) -> dict:
    net = result["net_return"]
    equity = result["equity"]
    days = len(result)
    trading_days = 252

    total_return = equity.iloc[-1] - 1
    cagr = equity.iloc[-1] ** (trading_days / max(days, 1)) - 1
    sharpe = np.sqrt(trading_days) * net.mean() / (net.std() + 1e-9)
    max_drawdown = result["drawdown"].min()
    win_rate = (net > 0).mean()

    return {
        "days": days,
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "win_rate": win_rate,
        "avg_daily_return": net.mean(),
        "vol_daily_return": net.std(),
    }


def main(cfg: BacktestConfig) -> None:
    df = load_features(cfg.split)
    positions = build_positions(df, cfg.signal_column, cfg.threshold)
    result = run_backtest(df, positions, cfg.cost_per_turnover)
    metrics = summarize(result)

    print("[BACKTEST] Split:", cfg.split)
    print("[BACKTEST] Signal column:", cfg.signal_column or "(fallback)")
    print("[BACKTEST] Threshold:", cfg.threshold)
    print("[BACKTEST] Cost per turnover:", cfg.cost_per_turnover)
    print("[BACKTEST] Metrics:")
    for k, v in metrics.items():
        print(f"  {k}: {v:.4f}")

    if cfg.output_equity:
        os.makedirs(os.path.dirname(cfg.output_equity), exist_ok=True)
        result.to_csv(cfg.output_equity, index=False)
        print(f"[BACKTEST] Saved equity curve to {cfg.output_equity}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simple NG futures backtest")
    parser.add_argument("--split", choices=list(SPLIT_TO_FILE.keys()), default="test", help="Which features split to use")
    parser.add_argument("--signal-column", dest="signal_column", default="predicted_return", help="Signal column to use (fallback to momentum_20d)")
    parser.add_argument("--threshold", type=float, default=0.0, help="Signal threshold for entering positions")
    parser.add_argument("--cost", dest="cost_per_turnover", type=float, default=0.0005, help="Transaction cost per unit turnover (e.g., 0.0005 = 5bps)")
    parser.add_argument("--output", dest="output_equity", default=None, help="Optional path to save equity curve CSV")
    args = parser.parse_args()

    config = BacktestConfig(
        split=args.split,
        signal_column=args.signal_column,
        threshold=args.threshold,
        cost_per_turnover=args.cost_per_turnover,
        output_equity=args.output_equity,
    )
    main(config)
