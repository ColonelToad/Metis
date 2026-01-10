"""
Demo: simple order book simulation over test features.
- Seeds book with passive liquidity around prior close
- Takes market orders based on momentum_20d sign
- Reports basic PnL using trade fills
"""
import os
import random
import math
import pandas as pd
from research.simulator.order_book import OrderBook

FEATURES_PATH = os.path.join("data", "features", "test_features.csv")


def run_demo():
    df = pd.read_csv(FEATURES_PATH)
    df["date"] = pd.to_datetime(df["date"])  # ensure datetime
    df = df.sort_values("date").reset_index(drop=True)

    ob = OrderBook(tick_size=0.001)
    position = 0.0
    cash = 0.0

    for i in range(len(df)):
        row = df.iloc[i]
        close = float(row["close"]) if not math.isnan(row["close"]) else None
        momentum = float(row.get("momentum_20d", 0.0))
        if close is None:
            continue

        # seed passive liquidity around close
        spread = 0.01  # $0.01 spread
        size = 1.0
        ob.submit_limit("buy", close - spread/2, size)
        ob.submit_limit("sell", close + spread/2, size)

        # take a position based on momentum sign
        if momentum > 0:
            ob.submit_market("buy", 1.0)
        elif momentum < 0:
            ob.submit_market("sell", 1.0)

        # mark-to-market using mid price
        mid = ob.mid_price()
        if mid is not None:
            # Update PnL from today's trades
            while ob.trades:
                tr = ob.trades.pop(0)
                if tr.buy_id < tr.sell_id:  # heuristic; we don't distinguish maker/taker here
                    # if our order id is lower, assume we participated; simplistic
                    pass
                # Position and cash tracking
                if row.get("momentum_20d", 0.0) > 0:
                    position += tr.qty
                    cash -= tr.qty * tr.price
                elif row.get("momentum_20d", 0.0) < 0:
                    position -= tr.qty
                    cash += tr.qty * tr.price

    # Final mark-to-market using last close
    last_close = float(df.iloc[-1]["close"]) if not math.isnan(df.iloc[-1]["close"]) else 0.0
    equity = cash + position * last_close
    print(f"[SIM] Final position: {position:.2f} contracts")
    print(f"[SIM] Cash: {cash:.2f}")
    print(f"[SIM] Equity (MTM at last close): {equity:.2f}")


if __name__ == "__main__":
    run_demo()
