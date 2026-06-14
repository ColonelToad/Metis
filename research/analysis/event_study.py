"""
NG Futures Event Study
======================
Tags major price shock events from notes/Event.md and measures:
  - Event window price response [-20, +30] trading days
  - EIA storage surprise (actual vs 5-year seasonal average) correlation
  - Cross-source lead/lag: which series move before price?
  - Rolling correlations for the 2026 high-frequency window (LMP + weather)

Data sources used:
  - ng_futures_daily  (2000-2026, primary target)
  - cme_futures_daily (2016-2026, higher coverage)
  - eia_storage       (2014-2026, weekly)
  - bls_ppi           (2016-2026, monthly)
  - weather_observations (2023-2026, temperature)
  - grid_lmp          (Jan-Jun 2026, 5-min LMP)

Run from repo root:
    python research/analysis/event_study.py
Outputs saved to research/analysis/output/
"""

import sqlite3
import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

# -- Paths --------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "metis.db"
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

plt.style.use("seaborn-v0_8-darkgrid")
sns.set_palette("husl")

# -- Event Catalog -------------------------------------------------------------
# Sourced from notes/Event.md — major NG price shock events
EVENTS = [
    {
        "name": "Winter Storm Uri",
        "date": "2021-02-10",
        "end": "2021-02-20",
        "type": "demand_shock",
        "description": "Polar vortex collapse; Texas grid failure; NG spot hit $23+/MMBtu",
        "expected_direction": "up",
    },
    {
        "name": "Russia Invades Ukraine",
        "date": "2022-02-24",
        "end": "2022-02-24",
        "type": "supply_shock",
        "description": "European supply crisis; HH ran up on LNG export demand surge",
        "expected_direction": "up",
    },
    {
        "name": "2022 Summer Peak",
        "date": "2022-08-08",
        "end": "2022-08-08",
        "type": "demand_peak",
        "description": "Henry Hub hit $9.68 intraday — highest since 2008 on heat + LNG demand",
        "expected_direction": "up",
    },
    {
        "name": "Freeport LNG Explosion",
        "date": "2022-06-08",
        "end": "2022-06-08",
        "type": "supply_shock",
        "description": "2 bcf/d export capacity offline; US storage surged; HH prices fell",
        "expected_direction": "down",
    },
    {
        "name": "Winter Storm Elliott",
        "date": "2022-12-22",
        "end": "2022-12-26",
        "type": "demand_shock",
        "description": "Bomb cyclone across US; demand surge but production freeze-offs",
        "expected_direction": "up",
    },
]


# -- Data Loaders -------------------------------------------------------------

def load_ng_prices(conn: sqlite3.Connection) -> pd.DataFrame:
    """Load NG futures daily prices, prefer cme_futures_daily where available."""
    ng = pd.read_sql(
        "SELECT date, open, high, low, close, volume FROM ng_futures_daily ORDER BY date",
        conn,
        parse_dates=["date"],
    )
    cme = pd.read_sql(
        """SELECT date, open, high, low, close
           FROM cme_futures_daily
           WHERE contract_type = 'NG'
           ORDER BY date""",
        conn,
        parse_dates=["date"],
    )
    # Deduplicate: use CME where it overlaps (higher quality), ng_futures elsewhere
    ng = ng.set_index("date")
    cme = cme.set_index("date")
    combined = ng[["close"]].copy()
    combined.loc[cme.index, "close"] = cme["close"]
    combined = combined.sort_index().dropna()
    combined["return"] = combined["close"].pct_change()
    combined["log_return"] = np.log(combined["close"] / combined["close"].shift(1))
    combined["cumulative_return"] = (1 + combined["return"]).cumprod() - 1
    return combined


def load_eia_storage(conn: sqlite3.Connection) -> pd.DataFrame:
    """Load EIA weekly storage and compute injection/withdrawal + seasonal surprise.

    The eia_storage table stores multiple regional series per timestamp with area-name='NA'.
    The national total is the maximum value per timestamp.
    """
    df = pd.read_sql(
        """SELECT timestamp as date, MAX(CAST(storage_bcf AS REAL)) as storage_bcf
           FROM eia_storage
           GROUP BY timestamp
           ORDER BY date""",
        conn,
        parse_dates=["date"],
    )
    df = df.set_index("date").sort_index()
    df["injection"] = df["storage_bcf"].diff()  # positive = injection, negative = withdrawal
    df["week_of_year"] = df.index.isocalendar().week.astype(int)

    # 5-year seasonal average (rolling, not look-ahead)
    seasonal_avg = (
        df.groupby("week_of_year")["injection"]
        .transform(lambda x: x.expanding().mean().shift(1))
    )
    df["injection_surprise"] = df["injection"] - seasonal_avg
    df["storage_yoy"] = df["storage_bcf"] - df["storage_bcf"].shift(52)
    return df


def load_weather(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql(
        """SELECT timestamp as date, location, temp_mean_f, temp_min_f, temp_max_f
           FROM weather_observations ORDER BY date""",
        conn,
        parse_dates=["date"],
    )
    # Average across all locations
    daily = (
        df.groupby("date")[["temp_mean_f", "temp_min_f", "temp_max_f"]]
        .mean()
        .sort_index()
    )
    daily["hdd"] = np.maximum(65 - daily["temp_mean_f"], 0)
    daily["cdd"] = np.maximum(daily["temp_mean_f"] - 65, 0)
    return daily


def load_lmp_daily(conn: sqlite3.Connection) -> pd.DataFrame:
    """Aggregate 5-min LMP to daily average price."""
    df = pd.read_sql(
        """SELECT date(timestamp) as date, AVG(lmp) as lmp_avg, AVG("Energy") as energy_avg
           FROM grid_lmp GROUP BY date(timestamp) ORDER BY date""",
        conn,
        parse_dates=["date"],
    )
    return df.set_index("date").sort_index()


def load_ppi(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql(
        """SELECT date, ppi_index, ppi_yoy_change, series_name
           FROM bls_ppi ORDER BY date""",
        conn,
        parse_dates=["date"],
    )
    # Keep the most relevant series (energy PPI if available, else all)
    energy = df[df["series_name"].str.contains("energy|fuel|gas", case=False, na=False)]
    if energy.empty:
        energy = df
    return energy.set_index("date").sort_index()


# -- Event Study --------------------------------------------------------------

def plot_event_windows(ng: pd.DataFrame, eia: pd.DataFrame) -> None:
    """Plot price response windows for each event."""
    PRE, POST = 20, 30

    fig, axes = plt.subplots(len(EVENTS), 2, figsize=(16, 4 * len(EVENTS)))
    fig.suptitle("NG Futures — Event Study Windows", fontsize=14, fontweight="bold", y=1.01)

    results = []

    for i, event in enumerate(EVENTS):
        ev_date = pd.Timestamp(event["date"])
        ax_price, ax_storage = axes[i]

        # Price window
        idx = ng.index.searchsorted(ev_date)
        start_idx = max(0, idx - PRE)
        end_idx = min(len(ng), idx + POST + 1)
        window = ng.iloc[start_idx:end_idx].copy()
        window["t"] = range(len(window))
        event_t = window.index.searchsorted(ev_date)

        # Cumulative return from T-PRE
        base_price = window["close"].iloc[0]
        window["cum_ret"] = (window["close"] / base_price - 1) * 100

        ax_price.plot(window.index, window["cum_ret"], color="#2196F3", linewidth=2)
        ax_price.axvline(ev_date, color="red", linestyle="--", linewidth=1.5, label="Event date")
        color = "#4CAF50" if event["expected_direction"] == "up" else "#F44336"
        ax_price.fill_between(
            window.index,
            0,
            window["cum_ret"],
            where=(window.index >= ev_date),
            alpha=0.2,
            color=color,
        )
        ax_price.set_title(f"{event['name']} ({event['date']})", fontsize=11, fontweight="bold")
        ax_price.set_ylabel("Cumulative return (%)")
        ax_price.axhline(0, color="gray", linewidth=0.8, linestyle=":")
        ax_price.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax_price.tick_params(axis="x", rotation=30)

        # EIA storage around event
        ev_start = ev_date - pd.Timedelta(days=PRE * 2)
        ev_end = ev_date + pd.Timedelta(days=POST * 3)
        eia_window = eia.loc[ev_start:ev_end]
        if not eia_window.empty:
            colors = ["#4CAF50" if v >= 0 else "#F44336" for v in eia_window["injection_surprise"]]
            ax_storage.bar(eia_window.index, eia_window["injection_surprise"], color=colors, width=5)
            ax_storage.axvline(ev_date, color="red", linestyle="--", linewidth=1.5)
            ax_storage.axhline(0, color="gray", linewidth=0.8)
            ax_storage.set_title("EIA Storage Surprise (Bcf vs seasonal avg)", fontsize=10)
            ax_storage.set_ylabel("Surprise (Bcf)")
            ax_storage.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
            ax_storage.tick_params(axis="x", rotation=30)
        else:
            ax_storage.text(0.5, 0.5, "No EIA data for this period",
                           ha="center", va="center", transform=ax_storage.transAxes)

        # Record metrics
        pre_return = window.loc[:ev_date, "return"].sum() if ev_date in window.index else None
        post = window.loc[ev_date:]
        post_5d = post.iloc[:6]["return"].sum() if len(post) >= 5 else None
        post_20d = post.iloc[:21]["return"].sum() if len(post) >= 20 else None
        results.append({
            "event": event["name"],
            "date": event["date"],
            "type": event["type"],
            "expected": event["expected_direction"],
            "pre_20d_return_pct": round((window["cum_ret"].iloc[event_t] if event_t < len(window) else np.nan), 2),
            "post_5d_return_pct": round(post_5d * 100 if post_5d else np.nan, 2),
            "post_20d_return_pct": round(post_20d * 100 if post_20d else np.nan, 2),
            "close_at_event": round(ng.loc[ng.index >= ev_date, "close"].iloc[0], 2) if (ng.index >= ev_date).any() else np.nan,
        })

    plt.tight_layout()
    out = OUTPUT_DIR / "event_windows.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"  Saved: {out}")
    plt.close(fig)

    df_results = pd.DataFrame(results)
    csv_out = OUTPUT_DIR / "event_metrics.csv"
    df_results.to_csv(csv_out, index=False)
    print(f"  Saved: {csv_out}")
    print()
    print(df_results.to_string(index=False))


# -- EIA Storage Surprise Correlation -----------------------------------------

def plot_eia_correlation(ng: pd.DataFrame, eia: pd.DataFrame) -> None:
    """Correlate EIA storage surprise with NG price moves at various lags."""
    # Resample NG to weekly (Friday close)
    ng_weekly = ng["close"].resample("W-FRI").last().pct_change() * 100
    ng_weekly.name = "ng_return_pct"

    df = eia[["injection", "injection_surprise", "storage_yoy"]].copy()
    df = df.join(ng_weekly, how="inner").dropna()

    lags = range(-4, 5)  # -4 weeks (EIA leads) to +4 weeks (EIA lags)
    corr_injection = [df["ng_return_pct"].corr(df["injection"].shift(lag)) for lag in lags]
    corr_surprise = [df["ng_return_pct"].corr(df["injection_surprise"].shift(lag)) for lag in lags]
    corr_yoy = [df["ng_return_pct"].corr(df["storage_yoy"].shift(lag)) for lag in lags]

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle("EIA Storage -> NG Price: Lead/Lag Correlations", fontsize=13, fontweight="bold")

    lag_labels = [f"T{l:+d}w" for l in lags]
    bar_colors = ["#4CAF50" if c > 0 else "#F44336" for c in corr_surprise]

    for ax, corrs, title in zip(
        axes,
        [corr_injection, corr_surprise, corr_yoy],
        ["Raw Injection (Bcf)", "Injection Surprise (vs seasonal avg)", "Storage YoY (Bcf)"],
    ):
        colors = ["#4CAF50" if c > 0 else "#F44336" for c in corrs]
        ax.bar(lag_labels, corrs, color=colors)
        ax.axhline(0, color="gray", linewidth=0.8)
        ax.axvline(lag_labels[4], color="black", linewidth=0.8, linestyle=":")  # T=0
        ax.set_title(title, fontsize=10)
        ax.set_ylabel("Pearson r")
        ax.set_ylim(-0.5, 0.5)
        ax.tick_params(axis="x", rotation=45)

    plt.tight_layout()
    out = OUTPUT_DIR / "eia_lead_lag.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"  Saved: {out}")
    plt.close(fig)

    # Print top correlations
    best_lag = lags[np.argmax(np.abs(corr_surprise))]
    print(f"  Strongest EIA surprise correlation: lag={best_lag:+d}w, r={max(corr_surprise, key=abs):.3f}")


# -- 2026 High-Frequency Correlation (LMP + Weather) --------------------------

def plot_2026_correlations(ng: pd.DataFrame, lmp: pd.DataFrame, weather: pd.DataFrame) -> None:
    """Rolling 30-day correlations for the 2026 window where LMP and weather overlap."""
    start = pd.Timestamp("2026-01-01")
    ng_2026 = ng.loc[start:, "return"].dropna()

    if lmp.empty or weather.empty:
        print("  Skipping 2026 correlations — LMP or weather data unavailable")
        return

    lmp_2026 = lmp.loc[start:, "lmp_avg"]
    weather_2026 = weather.loc[start:, ["temp_mean_f", "hdd", "cdd"]]

    # Align on common dates
    combined = pd.DataFrame({"ng_return": ng_2026})
    combined = combined.join(lmp_2026.rename("lmp"), how="left")
    combined = combined.join(weather_2026, how="left")
    combined = combined.dropna(subset=["ng_return"])

    WINDOW = 30

    fig, axes = plt.subplots(2, 2, figsize=(14, 8))
    fig.suptitle("2026 Window — Rolling 30-Day Correlations with NG Returns", fontsize=13, fontweight="bold")

    pairs = [
        ("lmp", "Daily LMP vs NG Return", "#9C27B0"),
        ("temp_mean_f", "Mean Temperature vs NG Return", "#FF9800"),
        ("hdd", "Heating Degree Days vs NG Return", "#2196F3"),
        ("cdd", "Cooling Degree Days vs NG Return", "#F44336"),
    ]

    for ax, (col, title, color) in zip(axes.flat, pairs):
        if col not in combined.columns:
            ax.set_visible(False)
            continue
        rolling_corr = combined["ng_return"].rolling(WINDOW).corr(combined[col])
        ax.plot(rolling_corr.index, rolling_corr, color=color, linewidth=1.5)
        ax.axhline(0, color="gray", linewidth=0.8)
        ax.axhline(0.3, color="gray", linestyle=":", linewidth=0.8)
        ax.axhline(-0.3, color="gray", linestyle=":", linewidth=0.8)
        ax.set_title(title, fontsize=10)
        ax.set_ylabel("Rolling Pearson r")
        ax.set_ylim(-1, 1)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.tick_params(axis="x", rotation=30)

    plt.tight_layout()
    out = OUTPUT_DIR / "rolling_correlations_2026.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"  Saved: {out}")
    plt.close(fig)


# -- Full Price History Overview -----------------------------------------------

def plot_price_history(ng: pd.DataFrame) -> None:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 8), sharex=True)
    fig.suptitle("Henry Hub NG Futures — Price History with Event Markers", fontsize=13, fontweight="bold")

    ax1.plot(ng.index, ng["close"], color="#1565C0", linewidth=1, alpha=0.9)
    ax1.set_ylabel("Price ($/MMBtu)")
    ax1.set_yscale("log")

    for event in EVENTS:
        ev_date = pd.Timestamp(event["date"])
        color = "#4CAF50" if event["expected_direction"] == "up" else "#F44336"
        ax1.axvline(ev_date, color=color, linewidth=1.2, alpha=0.8)
        ax1.annotate(
            event["name"].split()[0],
            xy=(ev_date, ng.loc[ng.index >= ev_date, "close"].iloc[0] if (ng.index >= ev_date).any() else ng["close"].iloc[-1]),
            xytext=(8, 0),
            textcoords="offset points",
            fontsize=7,
            color=color,
            rotation=90,
            va="bottom",
        )

    rolling_vol = ng["log_return"].rolling(21).std() * np.sqrt(252) * 100
    ax2.fill_between(rolling_vol.index, rolling_vol, alpha=0.6, color="#FF5722")
    ax2.set_ylabel("Realized Vol % (21d)")
    ax2.set_xlabel("Date")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    plt.tight_layout()
    out = OUTPUT_DIR / "price_history.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"  Saved: {out}")
    plt.close(fig)


# -- Data Quality Report -------------------------------------------------------

def print_data_quality(conn: sqlite3.Connection) -> None:
    print("\n-- Data Quality Notes ----------------------------------------")
    checks = [
        ("drought_conditions", "date", "Timestamps appear as 1970-01-01 — likely epoch seconds stored as milliseconds (÷1000 fix needed)"),
        ("eia_production", "timestamp", "Only 14 rows (3 months) — effectively empty"),
        ("storm_events", None, "Table is empty"),
        ("port_la_lb_stats", None, "Table is empty"),
        ("scfi_freight_rates", None, "Table is empty"),
        ("fred_macro", "timestamp", "Only starts June 2024 — too short for pre-2024 event analysis"),
        ("weather_observations", "timestamp", "Only starts 2023 — too short for Uri/Freeport events"),
    ]
    for table, col, note in checks:
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM [{table}]")
            count = cur.fetchone()[0]
            print(f"  !  {table} ({count} rows): {note}")
        except Exception:
            pass
    print()


# -- Main ---------------------------------------------------------------------

def main() -> None:
    print(f"Connecting to {DB_PATH}")
    if not DB_PATH.exists():
        print(f"ERROR: database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)

    print("\n-- Loading data ----------------------------------------------")
    ng = load_ng_prices(conn)
    eia = load_eia_storage(conn)
    weather = load_weather(conn)
    lmp = load_lmp_daily(conn)

    print(f"  NG futures:   {len(ng)} days  ({ng.index[0].date()} -> {ng.index[-1].date()})")
    print(f"  EIA storage:  {len(eia)} weeks ({eia.index[0].date()} -> {eia.index[-1].date()})")
    print(f"  Weather:      {len(weather)} days  ({weather.index[0].date()} -> {weather.index[-1].date()})")
    print(f"  Grid LMP:     {len(lmp)} days  ({lmp.index[0].date()} -> {lmp.index[-1].date()})")

    print_data_quality(conn)

    print("-- Event window plots ----------------------------------------")
    plot_price_history(ng)
    plot_event_windows(ng, eia)

    print("\n-- EIA storage lead/lag analysis ----------------------------")
    plot_eia_correlation(ng, eia)

    print("\n-- 2026 high-frequency correlations -------------------------")
    plot_2026_correlations(ng, lmp, weather)

    conn.close()
    print(f"\nAll outputs written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
