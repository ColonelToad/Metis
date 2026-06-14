"""
EIA Injection-Surprise Strategy — Backtest Runner

Usage:
    python research/backtest/run_backtest.py
    python research/backtest/run_backtest.py --threshold 0.75 --holding-days 10
    python research/backtest/run_backtest.py --train-end 2020-12-31
    python research/backtest/run_backtest.py --regime-filter elevated  # only trade in elevated+ markets

--regime-filter options:
    elevated  : trade when prior 5-day peak regime >= elevated (|z| > 1.5)
    shock     : trade only in confirmed shock/crisis periods

Outputs (research/backtest/output/):
    equity_curve.png         - full equity curve with in/out-of-sample split
    equity_curve_filtered.png - regime-filtered version (when --regime-filter used)
    trade_log.csv            - every trade with P&L and regime tag
    metrics.txt              - printed report captured to file
"""
import argparse
import sqlite3
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH   = REPO_ROOT / "data" / "metis.db"
sys.path.insert(0, str(REPO_ROOT))

from research.backtest import signals as sig_module
from research.backtest import engine, metrics

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def plot_equity_curve(trades: pd.DataFrame, train_end: str | None, out_path: Path) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), gridspec_kw={"height_ratios": [3, 1, 1]})
    fig.suptitle("EIA Injection-Surprise Strategy — NG Futures", fontsize=13, fontweight="bold")

    dates = trades["exit_date"]
    equity = trades["net_pnl"].cumsum()
    roll_max = equity.cummax()
    drawdown = equity - roll_max

    # Shade in-sample / out-of-sample
    ax0 = axes[0]
    if train_end:
        split = pd.Timestamp(train_end)
        ax0.axvspan(dates.iloc[0], split, alpha=0.06, color="steelblue", label="In-sample")
        ax0.axvspan(split, dates.iloc[-1], alpha=0.06, color="darkorange", label="Out-of-sample")

    ax0.plot(dates, equity, color="steelblue", linewidth=1.5, label="Equity ($)")
    ax0.axhline(0, color="gray", linewidth=0.6, linestyle="--")
    ax0.set_ylabel("Cumulative P&L ($)")
    ax0.legend(loc="upper left", fontsize=8)
    ax0.grid(True, alpha=0.3)

    # Drawdown
    axes[1].fill_between(dates, drawdown, 0, color="crimson", alpha=0.5)
    axes[1].set_ylabel("Drawdown ($)")
    axes[1].grid(True, alpha=0.3)

    # Signal z-score
    axes[2].bar(
        trades["trade_date"],
        trades["surprise_z"],
        color=["steelblue" if d == "long" else "tomato" for d in trades["direction"]],
        alpha=0.6,
        width=5,
    )
    axes[2].axhline(0, color="gray", linewidth=0.6)
    axes[2].set_ylabel("Surprise z-score")
    axes[2].set_xlabel("Date")
    axes[2].grid(True, alpha=0.3)

    long_patch  = mpatches.Patch(color="steelblue", alpha=0.6, label="Long trade")
    short_patch = mpatches.Patch(color="tomato",    alpha=0.6, label="Short trade")
    axes[2].legend(handles=[long_patch, short_patch], fontsize=8)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {out_path}")


def load_regime_filter(min_regime: str) -> pd.Series:
    """
    Load prior-week peak regime from shock_regimes table.
    Returns a Series indexed by date with the 5-day trailing peak regime,
    shifted forward 5 days so we're using *last week's* state to gate *this week's* trade.
    """
    order = {"normal": 0, "elevated": 1, "shock": 2, "crisis": 3}
    threshold = order.get(min_regime, 1)

    conn = sqlite3.connect(DB_PATH)
    reg = pd.read_sql(
        "SELECT date, severity FROM shock_regimes ORDER BY date",
        conn, parse_dates=["date"],
    ).set_index("date")
    conn.close()

    # 5-day trailing peak severity, then shift 5 forward (use last week, not current week)
    peak = reg["severity"].rolling(5, min_periods=1).max().shift(5)
    return (peak >= threshold).rename("regime_ok")


def main() -> None:
    parser = argparse.ArgumentParser(description="EIA injection-surprise backtest")
    parser.add_argument("--threshold",     type=float, default=0.5,
                        help="EIA z-score threshold to take a position (default 0.5)")
    parser.add_argument("--holding-days",  type=int,   default=5,
                        help="Trading days to hold each trade (default 5)")
    parser.add_argument("--train-end",     type=str,   default="2022-12-31",
                        help="In-sample cutoff date (default 2022-12-31)")
    parser.add_argument("--regime-filter", type=str,   default=None,
                        choices=["elevated", "shock"],
                        help="Only trade when prior 5-day peak regime >= this level")
    args = parser.parse_args()

    print("Loading price data...")
    prices = sig_module.load_ng_prices()
    print(f"  NG prices: {prices.index[0].date()} -> {prices.index[-1].date()}  ({len(prices)} days)")

    print("Building EIA signal...")
    eia_signal = sig_module.load_eia_signal(threshold=args.threshold)
    n_trades_possible = (eia_signal["signal"] != 0).sum()
    print(f"  Signal rows: {len(eia_signal)}  |  Active signals: {n_trades_possible}")

    # Apply regime filter before engine (no look-ahead: uses prior week's regime)
    if args.regime_filter:
        print(f"Applying regime filter: prior regime >= '{args.regime_filter}'")
        regime_ok = load_regime_filter(args.regime_filter)
        # Align to EIA signal dates; only keep rows where regime was elevated/shock last week
        aligned = regime_ok.reindex(eia_signal.index, method="ffill")
        n_before = (eia_signal["signal"] != 0).sum()
        eia_signal = eia_signal.copy()
        eia_signal.loc[~aligned.fillna(False), "signal"] = 0
        n_after = (eia_signal["signal"] != 0).sum()
        print(f"  Trades before filter: {n_before}  |  After filter: {n_after}")

    print("Running backtest...")
    trades = engine.run(
        signals=eia_signal,
        prices=prices,
        holding_days=args.holding_days,
        train_end=args.train_end,
    )
    print(f"  Executed trades: {len(trades)}")

    if trades.empty:
        print("No trades generated. Check threshold, date range, or regime filter.")
        sys.exit(1)

    # Add regime tags
    trades = metrics.tag_regimes(trades)

    # ── Print reports ──────────────────────────────────────────────────────────
    in_sample  = trades[trades["sample"] == "in_sample"]
    out_sample = trades[trades["sample"] == "out_of_sample"]

    metrics.print_report(trades,       label="FULL PERIOD")
    if not in_sample.empty:
        metrics.print_report(in_sample,  label=f"IN-SAMPLE  (through {args.train_end})")
    if not out_sample.empty:
        metrics.print_report(out_sample, label=f"OUT-OF-SAMPLE  ({args.train_end} ->)")

    # ── Save outputs ───────────────────────────────────────────────────────────
    suffix = f"_{args.regime_filter}" if args.regime_filter else ""
    trades_out = OUTPUT_DIR / f"trade_log{suffix}.csv"
    trades.to_csv(trades_out, index=False)
    print(f"\n  Saved: {trades_out}")

    plot_equity_curve(trades, args.train_end, OUTPUT_DIR / f"equity_curve{suffix}.png")

    # Capture full report to text file
    report_path = OUTPUT_DIR / f"metrics{suffix}.txt"
    with open(report_path, "w") as f:
        f.write(f"Strategy  : EIA Injection Surprise\n")
        f.write(f"Threshold : {args.threshold}\n")
        f.write(f"Holding   : {args.holding_days} trading days\n")
        f.write(f"Train end : {args.train_end}\n\n")
        for label, subset in [
            ("FULL PERIOD", trades),
            (f"IN-SAMPLE (through {args.train_end})", in_sample),
            (f"OUT-OF-SAMPLE ({args.train_end} ->)", out_sample),
        ]:
            if subset.empty:
                continue
            s = metrics.summary(subset)
            f.write(f"\n{'='*50}\n{label}\n{'='*50}\n")
            for k, v in s.items():
                f.write(f"  {k:<18}: {v}\n")
            f.write("\nBy year:\n")
            f.write(metrics.by_year(subset).to_string())
            f.write("\n\nBy regime:\n")
            f.write(metrics.by_regime(subset).to_string())
            f.write("\n")
    print(f"  Saved: {report_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
