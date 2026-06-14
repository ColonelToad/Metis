"""
Performance metrics computed from the trade log produced by engine.run().
"""
import numpy as np
import pandas as pd


# Known shock events for regime tagging (from event_study.py)
SHOCK_WINDOWS = [
    ("Winter Storm Uri",        "2021-02-01", "2021-03-15"),
    ("Russia-Ukraine",          "2022-02-24", "2022-05-01"),
    ("2022 Summer Peak",        "2022-07-01", "2022-09-30"),
    ("Freeport LNG Explosion",  "2022-06-01", "2022-08-31"),
    ("Winter Storm Elliott",    "2022-12-15", "2023-01-15"),
]


def _tag_regime(trade_date: pd.Timestamp) -> str:
    for name, start, end in SHOCK_WINDOWS:
        if pd.Timestamp(start) <= trade_date <= pd.Timestamp(end):
            return f"shock ({name})"
    return "normal"


def tag_regimes(trades: pd.DataFrame) -> pd.DataFrame:
    trades = trades.copy()
    trades["regime"] = trades["trade_date"].apply(_tag_regime)
    return trades


def summary(trades: pd.DataFrame) -> dict:
    """Core metrics for a slice of trades."""
    if trades.empty:
        return {}

    pnl = trades["net_pnl"]
    wins  = pnl[pnl > 0]
    losses = pnl[pnl <= 0]

    # Weekly Sharpe: treat each trade as one weekly observation
    sharpe = (pnl.mean() / pnl.std() * np.sqrt(52)) if pnl.std() > 0 else np.nan

    # Sortino: downside deviation only
    downside = pnl[pnl < 0]
    sortino_denom = np.sqrt((downside**2).mean()) * np.sqrt(52) if len(downside) > 0 else np.nan
    sortino = (pnl.mean() * np.sqrt(52) / sortino_denom) if sortino_denom and sortino_denom > 0 else np.nan

    # Max drawdown on equity curve
    eq = pnl.cumsum()
    roll_max = eq.cummax()
    drawdown = eq - roll_max
    max_dd = drawdown.min()

    # Profit factor
    gross_win  = wins.sum()
    gross_loss = abs(losses.sum())
    pf = gross_win / gross_loss if gross_loss > 0 else np.inf

    return {
        "n_trades":      len(trades),
        "hit_rate":      round(len(wins) / len(trades), 3),
        "profit_factor": round(pf, 2),
        "sharpe":        round(sharpe, 2),
        "sortino":       round(sortino, 2),
        "avg_win":       round(wins.mean(), 0) if len(wins) > 0 else 0,
        "avg_loss":      round(losses.mean(), 0) if len(losses) > 0 else 0,
        "total_pnl":     round(pnl.sum(), 0),
        "max_drawdown":  round(max_dd, 0),
        "n_long":        int((trades["direction"] == "long").sum()),
        "n_short":       int((trades["direction"] == "short").sum()),
    }


def by_year(trades: pd.DataFrame) -> pd.DataFrame:
    trades = trades.copy()
    trades["year"] = trades["trade_date"].dt.year
    rows = []
    for yr, grp in trades.groupby("year"):
        m = summary(grp)
        m["year"] = yr
        rows.append(m)
    return pd.DataFrame(rows).set_index("year")[
        ["n_trades", "hit_rate", "profit_factor", "sharpe", "total_pnl", "max_drawdown"]
    ]


def by_regime(trades: pd.DataFrame) -> pd.DataFrame:
    trades = tag_regimes(trades)
    rows = []
    for regime, grp in trades.groupby("regime"):
        m = summary(grp)
        m["regime"] = regime
        rows.append(m)
    return pd.DataFrame(rows).set_index("regime")[
        ["n_trades", "hit_rate", "profit_factor", "sharpe", "total_pnl"]
    ]


def print_report(trades: pd.DataFrame, label: str = "") -> None:
    if label:
        print(f"\n{'='*60}")
        print(f"  {label}")
        print(f"{'='*60}")

    s = summary(trades)
    print(f"\n  Trades     : {s['n_trades']}  (long={s['n_long']}, short={s['n_short']})")
    print(f"  Hit rate   : {s['hit_rate']:.1%}")
    print(f"  Profit fac : {s['profit_factor']:.2f}")
    print(f"  Sharpe     : {s['sharpe']:.2f}  (annualised, weekly obs)")
    print(f"  Sortino    : {s['sortino']:.2f}")
    print(f"  Avg win    : ${s['avg_win']:,.0f}   Avg loss: ${s['avg_loss']:,.0f}")
    print(f"  Total P&L  : ${s['total_pnl']:,.0f}")
    print(f"  Max DD     : ${s['max_drawdown']:,.0f}")

    print(f"\n  -- By year --")
    print(by_year(trades).to_string())

    print(f"\n  -- By regime --")
    print(by_regime(trades).to_string())
