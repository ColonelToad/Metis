"""
Event-driven backtest engine for EIA injection-surprise strategy.

Each EIA report week generates at most one trade:
  Entry : open of the week-ending Friday (= EIA timestamp)
  Exit  : close after `holding_days` trading days
  Size  : 1 NG futures contract = 10,000 MMBtu
  Costs : $50 round-trip (exchange fees + 1 tick slippage each way)
"""
import pandas as pd
import numpy as np
from typing import Optional

CONTRACT_SIZE = 10_000   # MMBtu per contract
COST_PER_RT  = 50.0     # USD round-trip transaction cost


def run(
    signals: pd.DataFrame,
    prices: pd.DataFrame,
    holding_days: int = 5,
    train_end: Optional[str] = None,
) -> pd.DataFrame:
    """
    Parameters
    ----------
    signals      : output of signals.load_eia_signal(); index = trade_date (Friday)
    prices       : daily OHLCV with DatetimeIndex; must include open and close
    holding_days : number of trading days to hold each position
    train_end    : if set, tag each trade as in_sample / out_of_sample

    Returns
    -------
    trades : DataFrame with one row per executed trade
    """
    price_dates = prices.index.sort_values()
    records = []

    for trade_date, row in signals.iterrows():
        if row["signal"] == 0:
            continue

        # Find entry date: first trading day >= trade_date
        future_dates = price_dates[price_dates >= trade_date]
        if len(future_dates) == 0:
            continue
        entry_date = future_dates[0]

        # Find exit date: holding_days trading days after entry
        entry_pos = price_dates.get_loc(entry_date)
        exit_pos = entry_pos + holding_days
        if exit_pos >= len(price_dates):
            continue
        exit_date = price_dates[exit_pos]

        entry_price = prices.loc[entry_date, "open"]
        exit_price  = prices.loc[exit_date, "close"]

        if pd.isna(entry_price) or pd.isna(exit_price):
            continue

        direction = row["signal"]  # 1 = long, -1 = short
        gross_pnl = direction * (exit_price - entry_price) * CONTRACT_SIZE
        net_pnl   = gross_pnl - COST_PER_RT

        sample = "in_sample"
        if train_end and trade_date > pd.Timestamp(train_end):
            sample = "out_of_sample"

        records.append({
            "trade_date":   trade_date,
            "entry_date":   entry_date,
            "exit_date":    exit_date,
            "direction":    "long" if direction == 1 else "short",
            "surprise_z":   round(row["surprise_z"], 3),
            "entry_price":  round(entry_price, 4),
            "exit_price":   round(exit_price, 4),
            "gross_pnl":    round(gross_pnl, 2),
            "net_pnl":      round(net_pnl, 2),
            "sample":       sample,
        })

    trades = pd.DataFrame(records)
    if not trades.empty:
        trades["equity"] = trades["net_pnl"].cumsum()
    return trades
