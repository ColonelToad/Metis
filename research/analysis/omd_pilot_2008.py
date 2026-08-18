"""
OMD Pilot: 2008 GFC Precursor Analysis

Computes three Observable Matrix Dynamics observables across the 2005-2009
window to test whether the 2008 GFC shows a measurable endogenous precursor
signature in the NG + energy equity universe:

  1. Mean correlation -- rolling pairwise return correlation across the equity
     cross-section. Rises into endogenous crises (Halperin 2026, confirmed for
     2008 GFC at 126-day and 504-day lookbacks).

  2. Participation ratio (effective factor count) -- (Σλi)² / Σλi² where λ
     are eigenvalues of the rolling correlation matrix. Falls as co-movement
     concentrates. Anti-correlated with mean correlation by construction.

  3. Market-factor share -- λ1 / Σλ. Rises as the leading eigenvalue dominates.
     Spikes most sharply at crisis onset.

  4. Commutator norm (secondary) -- ||[C(t_ref), C(t)]||_F, the Frobenius norm
     of the commutator between the current and a pre-crisis reference correlation
     matrix. Measures how fast the eigenbasis is rotating. Spikes at onset.

The canonical event window for the 2008 GFC is:
  - Pre-crisis anchor: 2007-01-01 (one year before onset in Halperin's framing)
  - Onset: 2008-07-01 (start of our shock_events entry)
  - Peak: 2008-09-15 (Lehman collapse)
  - End: 2009-03-31 (end of our shock_events entry)

OMD paper finding to replicate: rising mean correlation and falling participation
ratio should be visible in the 2007 pre-onset window, with the commutator spiking
at onset. If we see this in the NG universe, it validates the OMD approach for
energy infrastructure shock detection. If we don't, that itself is diagnostic --
it tells us the NG equity universe has different correlation dynamics than the
S&P 500 cross-section Halperin studied.

Run from C:\\Users\\legot\\Metis:
    python research/analysis/omd_pilot_2008.py
"""
import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parents[2]))
load_dotenv()

DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
engine = create_engine(DB_URL)

# Full pilot window -- 2 years before onset through 1 year after end
PILOT_START = "2004-06-01"
PILOT_END   = "2010-12-31"

# Canonical event markers from shock_events catalog
PRE_CRISIS_ANCHOR = pd.Timestamp("2007-01-01")
ONSET             = pd.Timestamp("2008-07-01")
LEHMAN            = pd.Timestamp("2008-09-15")
CRISIS_END        = pd.Timestamp("2009-03-31")

# Lookback windows matching the OMD paper's three tested windows
LOOKBACKS = {
    "126d": 126,   # ~6 months, resolves onset sharply
    "252d": 252,   # ~1 year, standard
    "504d": 504,   # ~2 years, used by Halperin as primary
}

# Equity universe: use the tickers that have coverage back to 2005
TICKERS = ["XLE", "XOP", "EQT", "AR", "CNX", "RRC", "KMI", "WMB", "EPD", "ET",
           "NEE", "D", "SO", "DUK"]


# ── Data loading ──────────────────────────────────────────────────────────────

def load_returns() -> pd.DataFrame:
    """Load daily log-returns for the equity universe and NG price."""
    with engine.connect() as conn:
        # Equity prices
        eq = pd.read_sql(text("""
            SELECT DATE(timestamp) as date, ticker, close
            FROM stock_prices
            WHERE ticker IN ({tickers})
              AND timestamp >= '{start}'
              AND timestamp <= '{end}'
            ORDER BY date, ticker
        """.format(
            tickers=",".join(f"'{t}'" for t in TICKERS),
            start=PILOT_START, end=PILOT_END
        )), conn)

        # NG futures price
        ng = pd.read_sql(text("""
            SELECT DATE(date) as date, close as ng_close
            FROM ng_futures_daily
            WHERE date >= :start AND date <= :end
            ORDER BY date
        """), conn, params={"start": PILOT_START, "end": PILOT_END})

    # Pivot equities to wide format
    eq["date"] = pd.to_datetime(eq["date"])
    eq_wide = eq.pivot(index="date", columns="ticker", values="close")

    ng["date"] = pd.to_datetime(ng["date"])
    ng = ng.set_index("date")

    # Join on date
    prices = eq_wide.join(ng, how="inner")

    # Log returns -- drop first row (NaN)
    returns = np.log(prices / prices.shift(1)).iloc[1:]
    returns = returns.dropna(axis=1, thresh=int(len(returns) * 0.8))  # drop thin columns
    print(f"Return matrix: {returns.shape[0]} trading days x {returns.shape[1]} assets")
    print(f"Assets: {list(returns.columns)}")
    print(f"Date range: {returns.index.min().date()} to {returns.index.max().date()}")
    return returns


def load_fundamentals() -> pd.DataFrame:
    """Load EIA storage deviation from seasonal norm and WTI crude."""
    with engine.connect() as conn:
        storage = pd.read_sql(text("""
            SELECT DATE(timestamp) as date,
                   CAST(storage_bcf AS REAL) as storage_bcf
            FROM eia_storage
            WHERE timestamp >= :start AND timestamp <= :end
            ORDER BY timestamp
        """), conn, params={"start": PILOT_START, "end": PILOT_END})

        wti = pd.read_sql(text("""
            SELECT DATE(timestamp) as date, wti_crude_price as wti
            FROM fred_macro
            WHERE timestamp >= :start AND timestamp <= :end
              AND wti_crude_price IS NOT NULL
            ORDER BY timestamp
        """), conn, params={"start": PILOT_START, "end": PILOT_END})

    storage["date"] = pd.to_datetime(storage["date"])
    storage = storage.set_index("date").resample("W-FRI").last()

    wti["date"] = pd.to_datetime(wti["date"])
    wti = wti.set_index("date")

    # Compute storage 5-year deviation (rough proxy without full history going back 5 years)
    storage["storage_52w_avg"] = storage["storage_bcf"].rolling(52, min_periods=26).mean()
    storage["storage_deviation"] = storage["storage_bcf"] - storage["storage_52w_avg"]

    return storage, wti


# ── OMD Observables ───────────────────────────────────────────────────────────

def compute_correlation_observables(returns: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """
    Rolling computation of mean correlation, participation ratio, and
    market-factor share for a given lookback window.
    """
    dates = returns.index[lookback:]
    results = []

    for i, date in enumerate(dates):
        window = returns.iloc[i:i + lookback]
        # Drop any columns with too many NaN in this window
        window = window.dropna(axis=1, thresh=int(lookback * 0.7))
        window = window.fillna(0.0)
        if window.shape[1] < 3:
            continue

        C = window.corr().values  # N x N correlation matrix
        N = C.shape[0]

        # Mean correlation (off-diagonal mean)
        mask = ~np.eye(N, dtype=bool)
        mean_corr = C[mask].mean()

        # Eigenvalue decomposition
        eigenvalues = np.linalg.eigvalsh(C)
        eigenvalues = np.maximum(eigenvalues, 0)  # numerical floor at 0

        # Participation ratio (effective factor count)
        sum_lambda = eigenvalues.sum()
        sum_lambda_sq = (eigenvalues ** 2).sum()
        participation_ratio = (sum_lambda ** 2) / sum_lambda_sq if sum_lambda_sq > 0 else np.nan

        # Market-factor share
        lambda_max = eigenvalues[-1]  # eigvalsh returns ascending order
        market_share = lambda_max / sum_lambda if sum_lambda > 0 else np.nan

        results.append({
            "date": date,
            "mean_corr": mean_corr,
            "participation_ratio": participation_ratio,
            "market_share": market_share,
            "n_assets": N,
        })

    df = pd.DataFrame(results).set_index("date")
    return df


def compute_commutator_norm(returns: pd.DataFrame, lookback: int,
                             anchor_date: pd.Timestamp) -> pd.DataFrame:
    """
    Compute ||[C(anchor), C(t)]||_F -- the Frobenius norm of the commutator
    between the anchor correlation matrix and each subsequent date's matrix.
    Measures how fast the eigenbasis is rotating away from the pre-crisis state.
    """
    # Get the anchor correlation matrix
    anchor_idx = returns.index.searchsorted(anchor_date)
    anchor_window = returns.iloc[max(0, anchor_idx - lookback):anchor_idx]
    anchor_window = anchor_window.dropna(axis=1, thresh=int(lookback * 0.7))
    if anchor_window.shape[1] < 3:
        return pd.DataFrame()

    C_ref = anchor_window.corr().values
    common_cols = anchor_window.columns

    dates = returns.index[lookback:]
    results = []

    for i, date in enumerate(dates):
        if date < anchor_date:
            continue
        window = returns[common_cols].iloc[i:i + lookback].fillna(0.0)
        if len(window) < lookback * 0.7:
            continue
        C_t = window.corr().values
        commutator = C_ref @ C_t - C_t @ C_ref
        frob_norm = np.linalg.norm(commutator, "fro")
        results.append({"date": date, "commutator_norm": frob_norm})

    return pd.DataFrame(results).set_index("date")


# ── Lobbying signal ───────────────────────────────────────────────────────────

def load_lobbying_signal() -> pd.DataFrame:
    """Quarterly filing counts and reported income for ENG/FUE issue codes."""
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT lf.dt_posted, lf.income, lf.expenses
            FROM lobbying_filings lf
            JOIN lobbying_activities la ON lf.filing_uuid = la.filing_uuid
            WHERE la.general_issue_code IN ('ENG','FUE')
              AND lf.dt_posted >= :start AND lf.dt_posted <= :end
        """), conn, params={"start": PILOT_START, "end": PILOT_END})

    df["dt_posted"] = pd.to_datetime(df["dt_posted"], format="ISO8601", utc=True).dt.tz_localize(None)
    df["income"] = pd.to_numeric(df["income"], errors="coerce")
    df["quarter"] = df["dt_posted"].dt.to_period("Q")

    quarterly = df.groupby("quarter").agg(
        filing_count=("income", "count"),
        total_income=("income", "sum"),
    ).reset_index()
    quarterly["date"] = quarterly["quarter"].apply(lambda q: q.end_time.normalize())
    return quarterly.set_index("date")


# ── Plotting ──────────────────────────────────────────────────────────────────

def plot_omd_pilot(observables: dict, fundamentals: tuple,
                   lobbying: pd.DataFrame, save_path: str):
    """
    Four-panel plot matching the OMD paper's layout:
    1. NG price + WTI (the visible signal)
    2. Mean correlation at three lookbacks
    3. Participation ratio at three lookbacks
    4. Market-factor share + lobbying filing count overlay
    """
    storage, wti = fundamentals

    fig, axes = plt.subplots(4, 1, figsize=(14, 16), sharex=True)
    fig.suptitle("OMD Pilot: 2008 GFC Precursor in NG Energy Universe\n"
                 "Does endogenous fragility build before onset?", fontsize=13, y=0.98)

    colors = {"126d": "#2196F3", "252d": "#FF9800", "504d": "#4CAF50"}
    alpha_fill = 0.12

    def add_event_lines(ax):
        ax.axvline(PRE_CRISIS_ANCHOR, color="green", ls="--", lw=1.2, alpha=0.7,
                   label="Pre-crisis anchor (2007-01-01)")
        ax.axvline(ONSET, color="red", ls="--", lw=1.5, alpha=0.8,
                   label="Crisis onset (2008-07-01)")
        ax.axvline(LEHMAN, color="darkred", ls=":", lw=1.5, alpha=0.9,
                   label="Lehman collapse (2008-09-15)")
        ax.axvspan(ONSET, CRISIS_END, alpha=alpha_fill, color="red", label="_nolegend_")

    # Panel 1: Prices
    ax = axes[0]
    with engine.connect() as conn:
        ng_price = pd.read_sql(text(
            "SELECT DATE(date) as date, close FROM ng_futures_daily "
            "WHERE date >= :s AND date <= :e ORDER BY date"
        ), conn, params={"s": PILOT_START, "e": PILOT_END})
    ng_price["date"] = pd.to_datetime(ng_price["date"])
    ng_price = ng_price.set_index("date")

    ax2 = ax.twinx()
    ax.plot(ng_price.index, ng_price["close"], color="#1565C0", lw=1.2, label="NG Henry Hub ($/MMBtu)")
    ax2.plot(wti.index, wti["wti"], color="#E65100", lw=1.0, alpha=0.6, label="WTI Crude ($/bbl)")
    add_event_lines(ax)
    ax.set_ylabel("NG Price ($/MMBtu)", color="#1565C0")
    ax2.set_ylabel("WTI ($/bbl)", color="#E65100")
    ax.legend(loc="upper left", fontsize=8)
    ax2.legend(loc="upper right", fontsize=8)
    ax.set_title("Prices", fontsize=10)

    # Panel 2: Mean correlation
    ax = axes[1]
    for lb, df in observables.items():
        if "mean_corr" in df.columns:
            ax.plot(df.index, df["mean_corr"], color=colors[lb], lw=1.3,
                    alpha=0.85, label=f"{lb} lookback")
    add_event_lines(ax)
    ax.set_ylabel("Mean pairwise correlation")
    ax.set_title("Mean Cross-Sectional Correlation (should RISE into Type 1 onset)", fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # Panel 3: Participation ratio
    ax = axes[2]
    for lb, df in observables.items():
        if "participation_ratio" in df.columns:
            ax.plot(df.index, df["participation_ratio"], color=colors[lb], lw=1.3,
                    alpha=0.85, label=f"{lb} lookback")
    add_event_lines(ax)
    ax.set_ylabel("Participation ratio (effective factors)")
    ax.set_title("Effective Factor Count (should FALL into Type 1 onset)", fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # Panel 4: Market-factor share + lobbying
    ax = axes[3]
    for lb, df in observables.items():
        if "market_share" in df.columns:
            ax.plot(df.index, df["market_share"], color=colors[lb], lw=1.3,
                    alpha=0.85, label=f"{lb} market share")
    add_event_lines(ax)
    ax.set_ylabel("Market-factor share (λ₁/Σλ)")

    if not lobbying.empty:
        ax3 = ax.twinx()
        ax3.bar(lobbying.index, lobbying["filing_count"], width=60, alpha=0.25,
                color="purple", label="ENG/FUE lobbying filings (quarterly)")
        ax3.set_ylabel("Lobbying filing count", color="purple")
        ax3.legend(loc="upper right", fontsize=8)

    ax.set_title("Market-Factor Share + Energy Lobbying Activity", fontsize=10)
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.3)

    for ax in axes:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7]))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    print(f"Plot saved to {save_path}")
    plt.close()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Loading return data...")
    returns = load_returns()

    print("\nLoading fundamentals...")
    storage, wti = load_fundamentals()

    print("\nLoading lobbying signal...")
    lobbying = load_lobbying_signal()
    print(f"Lobbying: {len(lobbying)} quarterly observations in window")

    print("\nComputing OMD observables...")
    observables = {}
    for lb_name, lb_days in LOOKBACKS.items():
        print(f"  Computing {lb_name} ({lb_days}-day rolling window)...")
        obs = compute_correlation_observables(returns, lb_days)
        comm = compute_commutator_norm(returns, lb_days, PRE_CRISIS_ANCHOR)
        if not comm.empty:
            obs = obs.join(comm, how="left")
        observables[lb_name] = obs
        print(f"  {lb_name}: {len(obs)} dates, mean_corr range "
              f"[{obs['mean_corr'].min():.3f}, {obs['mean_corr'].max():.3f}]")

    # Print key diagnostic numbers at the three event markers
    print("\n=== Key OMD diagnostics at event markers ===")
    markers = {
        "Pre-crisis anchor (2007-01-01)": PRE_CRISIS_ANCHOR,
        "Crisis onset (2008-07-01)": ONSET,
        "Lehman collapse (2008-09-15)": LEHMAN,
        "Crisis end (2009-03-31)": CRISIS_END,
    }
    for lb_name, obs in observables.items():
        print(f"\n  {lb_name} lookback:")
        for label, marker in markers.items():
            # Find nearest available date
            nearest_idx = obs.index.searchsorted(marker)
            if nearest_idx >= len(obs):
                continue
            row = obs.iloc[nearest_idx]
            print(f"    {label}")
            print(f"      mean_corr={row['mean_corr']:.4f}  "
                  f"participation_ratio={row['participation_ratio']:.2f}  "
                  f"market_share={row['market_share']:.4f}")

    # Save results
    output_dir = Path("data/analysis")
    output_dir.mkdir(parents=True, exist_ok=True)

    for lb_name, obs in observables.items():
        out_path = output_dir / f"omd_pilot_2008_{lb_name}.csv"
        obs.to_csv(out_path)
        print(f"\nSaved {lb_name} observables to {out_path}")

    plot_path = str(output_dir / "omd_pilot_2008_plot.png")
    print("\nGenerating plot...")
    plot_omd_pilot(observables, (storage, wti), lobbying, plot_path)

    print("\nDone. The key question is whether mean_corr rises and")
    print("participation_ratio falls in the 2007 pre-onset window --")
    print("if so, the 2008 GFC shows an endogenous Type 1 precursor in")
    print("the NG energy universe, validating the OMD approach for Metis.")


if __name__ == "__main__":
    main()
