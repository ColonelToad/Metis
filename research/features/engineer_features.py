"""
Feature Engineering Pipeline
Extracts and aligns features from multiple SQLite data sources for LSTM training.

Features:
- Price-based: lagged returns (1d, 5d, 20d), volatility (20d rolling std)
- EIA: storage levels, production, YoY changes, surprises
- FRED: macro indicators (unemployment, interest rates, CRB index, etc.)
- BLS: Producer Price Index (energy cost inflation indicator)
- Census: Building permits (forward-looking construction/energy demand)
- Congress: energy-related bills and legislative activity
- Derived: momentum, mean reversion signals

Output: Aligned daily CSV with all features aligned to NG futures dates
"""

import os
import warnings
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import polars as pl
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

warnings.filterwarnings("ignore")

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
METIS_MODE = os.getenv("METIS_MODE", "DEV")

OUTPUT_DIR = "data/features"
os.makedirs(OUTPUT_DIR, exist_ok=True)


class FeatureEngineer:
    """Feature engineering pipeline for LSTM training."""

    def __init__(self, db_url: str, start_date: str = "2015-01-01"):
        """
        Initialize feature engineer.

        Args:
            db_url: SQLAlchemy database URL
            start_date: Start date for feature extraction (default: 2015 for recent data)
        """
        self.engine = create_engine(db_url)
        self.start_date = pd.to_datetime(start_date)
        self.df = None

    def load_price_data(self) -> pd.DataFrame:
        """
        Load NG futures price data, stitched best-source-first:

          1. cme_settlements   -- official CME daily settlements (direct,
             ingested since Aug 2026; authoritative OHLC/settle + full curve)
          2. cme_futures_daily -- Yahoo NG=F weekly bridge (covers the gap
             between ng_futures_daily's death and settlements going live;
             overlap-validated vs official settles at 0.00% mean diff incl.
             the Aug 20->21 front-month roll)
          3. ng_futures_daily  -- Yahoo history back to 2000 (dead since
             2026-01-08, retained as the historical base)

        Front month per day = lowest-rowid settlement row with a non-null
        settle (rows are stored in contract-chronological order). Volume for
        settlements days is summed across all contract months so it remains
        comparable to the curve-total volumes in the Yahoo series (keeps
        volume_ratio continuous across stitches).
        """
        # Tier 1: direct CME settlements (front month).
        # Volume = FRONT MONTH only: Yahoo's series carries front-month
        # volume too (verified -- curve totals run ~2.6x higher and would
        # break volume_ratio continuity at the stitch).
        q_front = """
        SELECT s.trade_date AS date, s.open, s.high, s.low, s.settle AS close,
               s.volume
        FROM cme_settlements s
        WHERE s.product = 'natural_gas' AND s.settle IS NOT NULL
          AND s.rowid = (SELECT MIN(s2.rowid) FROM cme_settlements s2
                         WHERE s2.product = s.product
                           AND s2.trade_date = s.trade_date
                           AND s2.settle IS NOT NULL)
        ORDER BY s.trade_date
        """
        with self.engine.connect() as conn:
            settle = pd.read_sql(text(q_front), conn)

        # Tier 2: Yahoo weekly bridge (dedupe known double-stamped rows)
        with self.engine.connect() as conn:
            bridge = pd.read_sql(
                text(
                    "SELECT date, open, high, low, close, volume FROM cme_futures_daily "
                    "WHERE contract_type='natural_gas' ORDER BY date"
                ),
                conn,
            )

        # Tier 3: historical base
        with self.engine.connect() as conn:
            hist = pd.read_sql(
                text(
                    "SELECT date, open, high, low, close, volume FROM ng_futures_daily "
                    "WHERE date >= :start_date ORDER BY date"
                ),
                conn,
                params={"start_date": self.start_date.isoformat()},
            )

        def _norm(d, fmt=None):
            d = d.copy()
            # Sources serialize dates differently (date-only, datetime,
            # mixed ISO variants); parse explicitly, coerce stragglers.
            d["date"] = pd.to_datetime(d["date"], format=fmt, errors="coerce")
            return d.dropna(subset=["date"]).sort_values("date")

        settle = _norm(settle, "%Y-%m-%d")
        bridge = _norm(bridge, "ISO8601")
        hist = _norm(hist)
        n_bridge_raw = len(bridge)
        bridge = bridge.drop_duplicates(subset="date", keep="first")
        settle["price_source"] = "cme_settlements"
        bridge["price_source"] = "cme_futures_daily_yahoo"
        hist["price_source"] = "yahoo_ng_futures_daily"

        # Priority: official settles win; then the ORIGINAL training-era
        # history (byte-continuity with what past features were built on);
        # the Yahoo weekly bridge exists solely to fill the gap between
        # ng_futures_daily's death and settlements going live.
        # kind="stable" is load-bearing: equal dates must resolve by concat
        # order, not quicksort whim.
        df = (
            pd.concat([settle, hist, bridge], ignore_index=True)
            .sort_values("date", kind="stable")
            .drop_duplicates(subset="date", keep="first")
            .reset_index(drop=True)
        )
        df = df[df["date"] >= self.start_date].reset_index(drop=True)

        if df.empty:
            print("[FEATURES] Warning: no price data found in any source")
            return df

        # Log returns
        df["log_return"] = np.log(df["close"] / df["close"].shift(1))
        df["return_1d"] = df["log_return"]
        df["return_5d"] = df["log_return"].rolling(5).sum().shift(1)
        df["return_20d"] = df["log_return"].rolling(20).sum().shift(1)

        # Volatility (annualized)
        df["volatility_20d"] = df["log_return"].rolling(20).std() * np.sqrt(252)
        df["volatility_5d"] = df["log_return"].rolling(5).std() * np.sqrt(252)

        # Price range and momentum
        df["price_range"] = (df["high"] - df["low"]) / df["close"]
        df["momentum_20d"] = (df["close"] - df["close"].shift(20)) / df["close"].shift(20)

        # Volume trend
        df["volume_ma_20d"] = df["volume"].rolling(20).mean()
        df["volume_ratio"] = df["volume"] / (df["volume_ma_20d"] + 1e-8)

        src_counts = df["price_source"].value_counts().to_dict()
        print(
            f"[FEATURES] Price spine stitched: {len(df)} rows, "
            f"{df['date'].min().date()} to {df['date'].max().date()}"
        )
        print(
            f"[FEATURES]   sources: {src_counts} " f"(bridge deduped {n_bridge_raw - len(bridge)})"
        )
        return df

    def load_eia_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Load EIA storage and production data, calculate surprises and YoY changes."""

        # EIA Storage
        query_storage = """
        SELECT timestamp as date, storage_bcf
        FROM eia_storage
        WHERE timestamp >= :start_date
        ORDER BY timestamp
        """

        eia_storage = pl.read_database(
            query_storage.replace(":start_date", f"'{self.start_date.isoformat()}'"),
            self.engine,
        )

        if not eia_storage.is_empty():
            eia_storage = (
                eia_storage.lazy()
                .with_columns(
                    pl.col("date").str.to_datetime(strict=False),
                    pl.col("storage_bcf").cast(pl.Float64, strict=False),
                )
                .sort("date")
                .with_columns(
                    # Same op order as pandas pct_change: (x - x.shift)/x.shift
                    (
                        (pl.col("storage_bcf") - pl.col("storage_bcf").shift(52))
                        / pl.col("storage_bcf").shift(52)
                    ).alias("eia_storage_yoy"),  # 1 year = ~52 weeks
                    pl.col("storage_bcf").diff().alias("eia_storage_change"),
                )
                .collect()
                .to_pandas()
            )

            # Merge to main dataframe using forward fill (weekly data to daily)
            df = df.merge(
                eia_storage[["date", "storage_bcf", "eia_storage_yoy", "eia_storage_change"]],
                on="date",
                how="left",
            )
            df["storage_bcf"] = df["storage_bcf"].fillna(method="ffill")
            df["eia_storage_yoy"] = df["eia_storage_yoy"].fillna(method="ffill")
            df["eia_storage_change"] = df["eia_storage_change"].fillna(method="ffill")

            print(
                f"[FEATURES] Loaded EIA storage data: {eia_storage['date'].min()} to {eia_storage['date'].max()}"
            )
        else:
            print("[FEATURES] Warning: No EIA storage data found")

        # EIA Production
        query_prod = """
        SELECT timestamp as date, production_mmcf
        FROM eia_production
        WHERE timestamp >= :start_date
        ORDER BY timestamp
        """

        eia_prod = pl.read_database(
            query_prod.replace(":start_date", f"'{self.start_date.isoformat()}'"),
            self.engine,
        )

        if not eia_prod.is_empty():
            eia_prod = (
                eia_prod.lazy()
                .with_columns(
                    pl.col("date").str.to_datetime(strict=False),
                    pl.col("production_mmcf").cast(pl.Float64, strict=False),
                )
                .sort("date")
                .with_columns(
                    (
                        (pl.col("production_mmcf") - pl.col("production_mmcf").shift(52))
                        / pl.col("production_mmcf").shift(52)
                    ).alias("eia_production_yoy"),
                    pl.col("production_mmcf").diff().alias("eia_production_change"),
                )
                .collect()
                .to_pandas()
            )

            df = df.merge(
                eia_prod[
                    ["date", "production_mmcf", "eia_production_yoy", "eia_production_change"]
                ],
                on="date",
                how="left",
            )
            df["production_mmcf"] = df["production_mmcf"].fillna(method="ffill")
            df["eia_production_yoy"] = df["eia_production_yoy"].fillna(method="ffill")
            df["eia_production_change"] = df["eia_production_change"].fillna(method="ffill")

            print(
                f"[FEATURES] Loaded EIA production data: {eia_prod['date'].min()} to {eia_prod['date'].max()}"
            )
        else:
            print("[FEATURES] Warning: No EIA production data found")

        return df

    def load_fred_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Load FRED macro indicators."""

        query = """
        SELECT timestamp as date, cpi_energy, retail_gas_price, 
               wti_crude_price, industrial_production, housing_starts, personal_consumption
        FROM fred_macro
        WHERE timestamp >= :start_date
        ORDER BY timestamp
        """

        fred_pl = pl.read_database(
            query.replace(":start_date", f"'{self.start_date.isoformat()}'"),
            self.engine,
        )

        if not fred_pl.is_empty():
            base_cols = [c for c in fred_pl.columns if c != "date"]
            fred = (
                fred_pl.lazy()
                .with_columns(
                    pl.col("date").str.to_datetime(strict=False),
                    *[pl.col(c).cast(pl.Float64, strict=False) for c in base_cols],
                )
                .sort("date")
                # Forward fill base columns first (sparse FRED data), then back fill
                .with_columns(
                    *[pl.col(c).forward_fill().backward_fill() for c in base_cols]
                )
                # YoY / MA over 4 quarters
                .with_columns(
                    *[
                        expr
                        for c in base_cols
                        for expr in (
                            ((pl.col(c) - pl.col(c).shift(4)) / pl.col(c).shift(4)).alias(
                                f"{c}_yoy"
                            ),
                            pl.col(c).rolling_mean(4).alias(f"{c}_ma"),
                        )
                    ]
                )
                .collect()
                .to_pandas()
            )

            # Calculate YoY changes for each indicator (4 quarters for FRED monthly/quarterly)
            derived_cols = []
            for col in base_cols:
                derived_cols.extend([f"{col}_yoy", f"{col}_ma"])

            df = df.merge(fred, on="date", how="left")

            # Forward fill ALL FRED columns (base + derived) to daily data
            all_fred_cols = base_cols + derived_cols
            for col in all_fred_cols:
                if col in df.columns:
                    df[col] = df[col].fillna(method="ffill").fillna(method="bfill")

            print(f"[FEATURES] Loaded {len(fred.columns)-1} FRED indicators")
        else:
            print("[FEATURES] Warning: No FRED data found")

        return df

    def load_bls_ppi_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Load BLS Producer Price Index (cost inflation indicator)."""

        query = """
        SELECT date, series_id, ppi_index, ppi_yoy_change
        FROM bls_ppi
        WHERE date >= :start_date
        ORDER BY date
        """

        # NOTE: pandas read retained deliberately -- bls_ppi stores mixed
        # SQLite types per column (TEXT numerics beside REALs), which breaks
        # polars read_database schema inference. Frame is monthly-tiny; the
        # merge_asof loop below stays pandas for the same reason.
        with self.engine.connect() as conn:
            ppi = pd.read_sql(text(query), conn, params={"start_date": self.start_date.isoformat()})

        if not ppi.empty:
            # NOTE: bls_ppi.date carries ingestion-time timestamps (sub-second precision),
            # not normalized calendar dates. An exact-date merge against ng_futures_daily
            # (midnight-normalized) previously matched zero rows for every PPI series,
            # silently producing 100%-NaN columns. Normalize first, then use merge_asof
            # (nearest prior date) rather than exact match, since PPI is monthly data and
            # an exact join still fails whenever the 1st of the month isn't a trading day.
            ppi["date"] = pd.to_datetime(ppi["date"]).dt.normalize()
            ppi = ppi.sort_values("date")
            df = df.sort_values("date")

            # Pivot to get each series as a column
            # For each series: take the PPI index and YoY change
            for series_id in ppi["series_id"].unique():
                series_data = ppi[ppi["series_id"] == series_id][
                    ["date", "ppi_index", "ppi_yoy_change"]
                ].copy()
                series_data.columns = ["date", f"ppi_index_{series_id}", f"ppi_yoy_{series_id}"]
                series_data = series_data.sort_values("date")
                df = pd.merge_asof(df, series_data, on="date", direction="backward")

            # Simple aggregate: average PPI across energy series
            ppi_cols = [c for c in df.columns if c.startswith("ppi_index_")]
            if ppi_cols:
                df["ppi_energy_avg"] = df[ppi_cols].mean(axis=1)

                # YoY aggregate
                ppi_yoy_cols = [c for c in df.columns if c.startswith("ppi_yoy_")]
                if ppi_yoy_cols:
                    df["ppi_yoy_avg"] = df[ppi_yoy_cols].mean(axis=1)

            n_populated = df[ppi_cols[0]].notna().sum() if ppi_cols else 0
            print(
                f"[FEATURES] Loaded BLS PPI data ({len(ppi['series_id'].unique())} series, "
                f"{n_populated}/{len(df)} rows populated post-merge_asof)"
            )
        else:
            print("[FEATURES] Warning: No BLS PPI data found")

        return df

    def load_census_permit_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Load Census building permits (forward-looking energy demand)."""

        query = """
        SELECT date, permit_count, permit_6m_rolling, permit_yoy_change, permit_bullish
        FROM census_permits
        WHERE date >= :start_date
        ORDER BY date
        """

        permits = (
            pl.read_database(
                query.replace(":start_date", f"'{self.start_date.isoformat()}'"),
                self.engine,
            )
            .lazy()
            .with_columns(pl.col("date").str.to_datetime(strict=False).dt.date())
            .sort("date")
            .collect()
            .to_pandas()
        )

        if not permits.empty:
            permits["date"] = pd.to_datetime(permits["date"])
            permits = permits[
                ["date", "permit_count", "permit_6m_rolling", "permit_yoy_change", "permit_bullish"]
            ]

            df = df.merge(permits, on="date", how="left")

            # Forward-looking signal: permits lead construction by ~3-6 months
            # Create lagged features to capture lead relationship
            df["permit_count_lag3m"] = df["permit_count"].shift(3)
            df["permit_bullish_lag3m"] = df["permit_bullish"].shift(3)

            print(f"[FEATURES] Loaded Census building permit data")
        else:
            print("[FEATURES] Warning: No Census permit data found")

        return df

    def load_congress_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Load Congress bill activity (total and energy-related)."""

        query = """
        SELECT timestamp as date, is_energy_related
        FROM congress_bills
        WHERE timestamp >= :start_date
        ORDER BY timestamp
        """

        congress = pl.read_database(
            query.replace(":start_date", f"'{self.start_date.isoformat()}'"),
            self.engine,
        )

        if not congress.is_empty():
            congress_agg = (
                congress.lazy()
                .with_columns(
                    pl.col("date").str.to_datetime(time_zone="UTC", strict=False)
                    .dt.replace_time_zone(None)
                    .dt.date()
                    .alias("day"),
                    pl.col("is_energy_related")
                    .cast(pl.Int64, strict=False)
                    .fill_null(0),
                )
                .drop_nulls("day")
                .group_by("day")
                .agg(
                    pl.len().cast(pl.Int64).alias("congress_bills_count"),
                    pl.col("is_energy_related")
                    .eq(1)
                    .sum()
                    .cast(pl.Int64)
                    .alias("congress_bills_energy_count"),
                )
                .sort("day")
                .collect()
                .to_pandas()
            )
            congress_agg.rename(columns={"day": "date"}, inplace=True)
            congress_agg["date"] = pd.to_datetime(congress_agg["date"])

            df = df.merge(congress_agg, on="date", how="left")
            df["congress_bills_count"] = df["congress_bills_count"].fillna(0)
            df["congress_bills_energy_count"] = df["congress_bills_energy_count"].fillna(0)

            df["congress_bills_ma"] = df["congress_bills_count"].rolling(20).mean()
            df["congress_bills_energy_ma"] = df["congress_bills_energy_count"].rolling(20).mean()

            print(
                f"[FEATURES] Loaded Congress bills: {len(congress_agg)} dates, total={congress_agg['congress_bills_count'].sum():.0f}, energy={congress_agg['congress_bills_energy_count'].sum():.0f}"
            )
        else:
            print("[FEATURES] Warning: No Congress data found")

        return df

    def load_weather_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Weather demand-forcing from NOAA CPC daily degree days
        (population-weighted and gas-heating-customer-weighted),
        expressed as deviations from the 1981-2010 daily climatology so
        the feature isolates weather SURPRISE rather than seasonality.
        Also merges hub-level observed temperatures from
        weather_observations (henry_hub_la, cushing_ok).

        Cumulative deviations reset at season anchors:
          - HDD season starts Jul 1 (withdrawal season)
          - CDD season starts Jan 1 (injection/cooling season)
        Rolling 7-day deviation sums capture short-term demand surprise;
        because they are computed on the full daily calendar BEFORE the
        merge, weekend degree days are not silently dropped.
        """

        query_dd = """
        SELECT date, weight_basis, degree_type, region_type, region, value
        FROM noaa_degree_days
        WHERE date >= :start_date
          AND (
            (region = 'CONUS' AND weight_basis = 'population'
             AND degree_type IN ('HDD','CDD'))
            OR (region = 'CONUS' AND weight_basis = 'utility_gas'
                AND degree_type = 'HDD')
            OR (weight_basis = 'population' AND degree_type = 'HDD'
                AND region IN ('3|East North Central', '4|West North Central'))
          )
        ORDER BY date
        """
        query_normals = """
        SELECT weight_basis, degree_type, region_type, region, mmdd, normal
        FROM noaa_dd_normals
        WHERE (region = 'CONUS' AND weight_basis = 'population'
               AND degree_type IN ('HDD','CDD'))
           OR (region = 'CONUS' AND weight_basis = 'utility_gas'
               AND degree_type = 'HDD')
           OR (weight_basis = 'population' AND degree_type = 'HDD'
               AND region IN ('3|East North Central', '4|West North Central'))
        """

        lookback_start = (self.start_date - pd.Timedelta(days=400)).isoformat()
        dd = pl.read_database(
            query_dd.replace(":start_date", f"'{lookback_start}'"), self.engine
        )
        normals = pl.read_database(query_normals, self.engine)

        if dd.is_empty():
            print("[FEATURES] Warning: no NOAA degree day data found")
            return df

        # Long frames keyed by series; normals joined on (mmdd, series) so
        # deviation = value - climatological normal for the same month/day.
        dev_long = (
            dd.lazy()
            .with_columns(
                pl.col("date").str.to_date(strict=False),
                (
                    pl.col("weight_basis")
                    + "_"
                    + pl.col("degree_type")
                    + "_"
                    + pl.col("region").str.split("|").list.first()
                ).alias("series"),
                pl.col("value").cast(pl.Float64, strict=False),
            )
            .drop_nulls(["date", "series"])
            .with_columns(pl.col("date").dt.strftime("%m%d").alias("mmdd"))
            .join(
                normals.lazy()
                .with_columns(
                    (
                        pl.col("weight_basis")
                        + "_"
                        + pl.col("degree_type")
                        + "_"
                        + pl.col("region").str.split("|").list.first()
                    ).alias("series"),
                    pl.col("normal").cast(pl.Float64, strict=False),
                )
                .select(["mmdd", "series", "normal"]),
                on=["mmdd", "series"],
                how="left",
            )
            .with_columns((pl.col("value") - pl.col("normal")).alias("dev"))
            .select(["date", "series", "dev"])
            .collect()
        )
        wide = dev_long.pivot(
            values="dev", index="date", on="series", aggregate_function="first"
        ).sort("date")
        series_cols = [c for c in wide.columns if c != "date"]

        # Season keys: HDD anchored Jul 1, CDD anchored Jan 1
        wide = wide.with_columns(
            pl.when(pl.col("date").dt.month() >= 7)
            .then(pl.col("date").dt.year())
            .otherwise(pl.col("date").dt.year() - 1)
            .alias("season_hdd"),
            pl.col("date").dt.year().alias("season_cdd"),
        )

        conus_pop_hdd = "population_HDD_CONUS"
        conus_pop_cdd = "population_CDD_CONUS"
        gas_hdd = "utility_gas_HDD_CONUS"

        def _dev(col: str, out: str) -> pl.Expr:
            return pl.col(col).alias(out) if col in series_cols else pl.lit(None).alias(out)

        def _cum(col: str, season: str, out: str) -> pl.Expr:
            if col not in series_cols:
                return pl.lit(None).alias(out)
            return pl.col(col).fill_null(0).cum_sum().over(season).alias(out)

        # Dev + season-cumsum pass (all expressions read the pivoted frame)
        wide = wide.with_columns(
            _dev(conus_pop_hdd, "hdd_conus_dev"),
            _cum(conus_pop_hdd, "season_hdd", "hdd_dev_cum_season"),
            _dev(conus_pop_cdd, "cdd_conus_dev"),
            _cum(conus_pop_cdd, "season_cdd", "cdd_dev_cum_season"),
            _dev(gas_hdd, "hdd_gas_conus_dev"),
            _cum(gas_hdd, "season_hdd", "hdd_gas_dev_cum_season"),
            *[
                _cum(f"population_HDD_{div}", "season_hdd", f"hdd_{tag}_dev_cum_season")
                for div, tag in (("3|East North Central", "enc"), ("4|West North Central", "wnc"))
            ],
        )
        # Rolling pass (reads the dev columns created above)
        wide = wide.with_columns(
            pl.col("hdd_conus_dev").rolling_sum(7).alias("hdd_conus_dev_7d"),
            pl.col("cdd_conus_dev").rolling_sum(7).alias("cdd_conus_dev_7d"),
        )

        keep = [
            "date",
            "hdd_conus_dev",
            "hdd_dev_cum_season",
            "cdd_conus_dev",
            "cdd_dev_cum_season",
            "hdd_gas_conus_dev",
            "hdd_gas_dev_cum_season",
            "hdd_enc_dev_cum_season",
            "hdd_wnc_dev_cum_season",
            "hdd_conus_dev_7d",
            "cdd_conus_dev_7d",
        ]
        # Drop all-null placeholder columns (series absent from this DB --
        # mirrors the pandas `if col in devs` guards)
        keep = [c for c in keep if not (c != "date" and wide[c].is_null().all())]
        feats = wide.select(keep).to_pandas()
        feats["date"] = pd.to_datetime(feats["date"])

        # Hub-level observed temperatures (weather_observations, open-meteo)
        query_hubs = """
        SELECT timestamp as date, location, temp_mean_f
        FROM weather_observations
        ORDER BY timestamp
        """
        with self.engine.connect() as conn:
            hubs = pd.read_sql(text(query_hubs), conn)
        if not hubs.empty:
            hubs["date"] = pd.to_datetime(hubs["date"])
            piv = hubs.pivot_table(
                index="date", columns="location", values="temp_mean_f", aggfunc="first"
            )
            rename = {"henry_hub_la": "temp_henry_hub", "cushing_ok": "temp_cushing"}
            piv = piv.rename(columns=rename)
            keep = [c for c in ("temp_henry_hub", "temp_cushing") if c in piv.columns]
            feats = feats.merge(piv[keep].reset_index(), on="date", how="left")

        merge_cols = [c for c in feats.columns if c != "date"]
        df = df.merge(feats[["date"] + merge_cols], on="date", how="left")

        print(f"[FEATURES] Weather features added: {merge_cols}")
        return df

    def load_cme_futures_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Load CME futures data (WTI, Brent, HO, RB) from cme_futures_daily table."""

        query = """
        SELECT date, contract_type, close, volatility_20d, ma_20
        FROM cme_futures_daily
        WHERE date >= :start_date
        ORDER BY date
        """

        cme_raw = pl.read_database(
            query.replace(":start_date", f"'{self.start_date.isoformat()}'"),
            self.engine,
        )

        if not cme_raw.is_empty():
            n_before = len(cme_raw)
            cme = (
                cme_raw.lazy()
                .with_columns(pl.col("date").str.to_datetime(strict=False).dt.date())
                .drop_nulls("date")
                # NOTE: cme_futures_daily carries duplicate rows per (date, contract_type) --
                # confirmed identical values under two different timestamp serializations,
                # same class of bug as the bls_ppi fix above, but hitting all 5 tracked
                # contracts rather than one series. Left unguarded, a plain merge fans out
                # 2x per contract, compounding to 2^5=32x across the 5 sequential merges below.
                .unique(subset=["date", "contract_type"], keep="first", maintain_order=True)
                # Secondary key pins per-date contract order (polars sort is
                # not stable); alphabetical matches the historical DB order.
                .sort(["date", "contract_type"])
                .collect()
            )
            n_after = len(cme)
            cme = cme.to_pandas()
            cme["date"] = pd.to_datetime(cme["date"])
            if n_after < n_before:
                print(f"[FEATURES] Deduped cme_futures_daily: {n_before} -> {n_after} rows")

            # Pivot contracts to get separate columns
            for contract in cme["contract_type"].unique():
                contract_data = cme[cme["contract_type"] == contract][
                    ["date", "close", "volatility_20d", "ma_20"]
                ]
                contract_data.columns = [
                    "date",
                    f"{contract}_close",
                    f"{contract}_volatility_20d",
                    f"{contract}_ma_20",
                ]

                # Merge to main dataframe
                df = df.merge(contract_data, on="date", how="left")

            # Calculate cross-asset spreads
            if "crude_oil_wti_close" in df.columns and "crude_oil_brent_close" in df.columns:
                df["wti_brent_spread"] = df["crude_oil_wti_close"] - df["crude_oil_brent_close"]
                df["wti_brent_spread_pct"] = (
                    df["wti_brent_spread"] / df["crude_oil_brent_close"] * 100
                ).fillna(0)

            # HO-WTI crack spread (heating oil relative to WTI)
            if "heating_oil_close" in df.columns and "crude_oil_wti_close" in df.columns:
                df["ho_wti_crack"] = df["heating_oil_close"] - (
                    df["crude_oil_wti_close"] * 0.42
                )  # Rough conversion
                df["ho_wti_spread_pct"] = (
                    df["ho_wti_crack"] / (df["crude_oil_wti_close"] * 0.42) * 100
                ).fillna(0)

            # NG correlation to crude (lead/lag to be analyzed separately)
            if "natural_gas_close" in df.columns and "crude_oil_wti_close" in df.columns:
                df["ng_wti_ratio"] = df["natural_gas_close"] / (df["crude_oil_wti_close"] + 1e-8)

            print(
                f"[FEATURES] Loaded CME futures data ({len(cme['contract_type'].unique())} contracts)"
            )
        else:
            print("[FEATURES] Warning: No CME futures data found")

        return df

    def load_power_lmp_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Load multi-ISO power LMP data from grid_lmp_multi_iso table."""

        query = """
        SELECT 
            DATE(timestamp) as date,
            iso,
            AVG(lmp) as lmp_avg
        FROM grid_lmp_multi_iso
        WHERE DATE(timestamp) >= :start_date
        GROUP BY DATE(timestamp), iso
        ORDER BY DATE(timestamp), iso
        """

        lmp_raw = pl.read_database(
            query.replace(":start_date", f"'{self.start_date.isoformat()}'"),
            self.engine,
        )

        if not lmp_raw.is_empty():
            n_before = len(lmp_raw)
            lmp = (
                lmp_raw.lazy()
                .with_columns(pl.col("date").str.to_date(strict=False))
                .drop_nulls("date")
                # Same class of duplicate-row risk as cme_futures_daily -- guard even though
                # the GROUP BY in the query above already aggregates within a calendar day;
                # this only protects against a second, differently-timestamped write of the
                # same (date, iso) slipping through as a distinct group.
                .unique(subset=["date", "iso"], keep="first", maintain_order=True)
                # Secondary key pins per-date ISO order (polars sort is not
                # stable); alphabetical matches the historical DB order.
                .sort(["date", "iso"])
                .collect()
                .to_pandas()
            )
            lmp["date"] = pd.to_datetime(lmp["date"])
            n_after = len(lmp)
            if n_after < n_before:
                print(f"[FEATURES] Deduped grid_lmp_multi_iso: {n_before} -> {n_after} rows")

            # Pivot ISOs to separate columns
            for iso in lmp["iso"].unique():
                iso_data = lmp[lmp["iso"] == iso][["date", "lmp_avg"]]
                iso_data.columns = ["date", f"lmp_{iso.lower()}_avg"]
                df = df.merge(iso_data, on="date", how="left")

            # Calculate composite LMP index (equal-weighted across ISOs)
            lmp_cols = [
                col for col in df.columns if col.startswith("lmp_") and col.endswith("_avg")
            ]
            if lmp_cols:
                df["lmp_composite_avg"] = df[lmp_cols].mean(axis=1)
                df["lmp_composite_std"] = df[lmp_cols].std(axis=1)
                df["lmp_composite_max"] = df[lmp_cols].max(axis=1)
                df["lmp_composite_min"] = df[lmp_cols].min(axis=1)

            # NG-to-power basis: how much more expensive is power relative to NG fuel value
            # Rough: LMP should correlate to NG price; basis = LMP - (NG_price * conversion_factor)
            if "natural_gas_close" in df.columns and "lmp_composite_avg" in df.columns:
                # Power generation efficiency: ~1 MMBtu of gas -> ~1 MWh with losses
                # LMP in $/MWh, NG in $/MMBtu, so direct comparison with efficiency factor
                df["ng_power_basis"] = df["lmp_composite_avg"] - (
                    df["natural_gas_close"] * 10
                )  # 10x factor for scale
                df["ng_power_basis_pct"] = (
                    df["ng_power_basis"] / (df["natural_gas_close"] * 10 + 1e-8) * 100
                ).fillna(0)

            print(f"[FEATURES] Loaded LMP data ({len(lmp['iso'].unique())} ISOs)")
        else:
            print("[FEATURES] Warning: No LMP data found")

        return df

    def load_eu_gas_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """EU gas balance: ENTSOG entry flows (total + Russian share),
        GIE AGSI storage (capacity-weighted fullness + net withdrawal),
        GIE ALSI LNG terminals (send-out + inventory).

        Previously ingested-but-dark (daily runs since 2021 for ENTSOG,
        2019 for GIE) — now merged at daily grain into the low-freq /
        fundamental branch. Same loader feeds the P1 smooth-vs-step test
        and the LNG-flows tensor slice; the 2023-03 ENTSOG window artifact
        is left raw here and cleaned in the pre-reg analysis, not here.
        """

        # --- ENTSOG nominations: daily EU entry total + Russian share ---
        entsog_q = """
        SELECT gas_day as date, point_label, SUM(value_kwh_d) as kwh_d
        FROM entsog_nominations
        WHERE gas_day >= :start_date
        GROUP BY gas_day, point_label
        ORDER BY gas_day
        """
        nom = pl.read_database(
            entsog_q.replace(":start_date", f"'{self.start_date.isoformat()}'"),
            self.engine,
        )

        if not nom.is_empty():
            eu = (
                nom.lazy()
                .with_columns(
                    pl.col("date").str.to_date(strict=False),
                    pl.col("kwh_d").cast(pl.Float64, strict=False).fill_null(0),
                    pl.col("point_label")
                    .str.contains("(?i)Greifswald|Lubmin|Mallnow|Sudzha")
                    .fill_null(False)
                    .alias("is_ru"),
                )
                .drop_nulls("date")
                .group_by("date")
                .agg(
                    pl.col("kwh_d").sum().alias("eu_entry_total_kwh"),
                    pl.col("kwh_d").filter(pl.col("is_ru")).sum().alias("eu_entry_ru_kwh"),
                )
                .sort("date")
                .collect()
                .to_pandas()
            )
            eu["date"] = pd.to_datetime(eu["date"])
            eu["eu_entry_ru_kwh"] = eu["eu_entry_ru_kwh"].fillna(0)
            eu["eu_entry_total_gwh"] = eu["eu_entry_total_kwh"] / 1e6
            eu["eu_russian_share"] = (
                eu["eu_entry_ru_kwh"] / eu["eu_entry_total_kwh"].replace(0, np.nan)
            ).fillna(0)
            # Artifact guard (detection only): flag months where EU entry
            # exceeds 3x the trailing median -- e.g. the 2023-03 window
            # with duplicated operator rows (~7732 TWh vs ~700 normal).
            med = eu["eu_entry_total_gwh"].rolling(90, min_periods=30).median()
            flagged = eu[eu["eu_entry_total_gwh"] > 3 * med]
            if not flagged.empty:
                print(
                    "[FEATURES] ENTSOG artifact warning: "
                    f"{len(flagged)} days exceed 3x trailing median "
                    f"(e.g. {flagged['date'].min().date()} "
                    f"{flagged['eu_entry_total_gwh'].max():.0f} GWh/d) -- "
                    "left raw, clean in pre-reg analysis"
                )
            df = df.merge(
                eu[["date", "eu_entry_total_gwh", "eu_russian_share"]],
                on="date",
                how="left",
            )
            print(
                f"[FEATURES] Loaded ENTSOG: {len(eu)} days, "
                f"RU share latest={eu['eu_russian_share'].iloc[-1]:.3f}"
            )
        else:
            print("[FEATURES] Warning: No ENTSOG data found")

        # --- GIE AGSI: EU-aggregate storage fullness + net withdrawal ---
        agsi_q = """
        SELECT gas_day as date,
               SUM(gas_in_storage_twh) as storage_twh,
               SUM(working_gas_volume_twh) as working_twh,
               SUM(net_withdrawal_gwh_d) as net_withdrawal_gwh_d
        FROM agsi_storage
        WHERE gas_day >= :start_date
        GROUP BY gas_day
        ORDER BY gas_day
        """
        agsi = pl.read_database(
            agsi_q.replace(":start_date", f"'{self.start_date.isoformat()}'"),
            self.engine,
        )

        if not agsi.is_empty():
            agsi = (
                agsi.lazy()
                .with_columns(
                    pl.col("date").str.to_date(strict=False),
                    pl.col("storage_twh").cast(pl.Float64, strict=False),
                    pl.col("working_twh").cast(pl.Float64, strict=False),
                    pl.col("net_withdrawal_gwh_d").cast(pl.Float64, strict=False),
                )
                .drop_nulls("date")
                .with_columns(
                    (
                        pl.col("storage_twh")
                        / pl.col("working_twh").replace(0, None)
                        * 100
                    ).alias("eu_storage_full_pct")
                )
                .sort("date")
                .collect()
                .to_pandas()
            )
            agsi["date"] = pd.to_datetime(agsi["date"])
            agsi.rename(
                columns={"net_withdrawal_gwh_d": "eu_net_withdrawal_gwh_d"}, inplace=True
            )
            df = df.merge(
                agsi[["date", "eu_storage_full_pct", "eu_net_withdrawal_gwh_d"]],
                on="date",
                how="left",
            )
            print(
                f"[FEATURES] Loaded AGSI: {len(agsi)} days, "
                f"EU fullness latest={agsi['eu_storage_full_pct'].iloc[-1]:.1f}%"
            )
        else:
            print("[FEATURES] Warning: No AGSI data found")

        # --- GIE ALSI: EU LNG send-out + inventory ---
        alsi_q = """
        SELECT gas_day as date,
               SUM(sendout_gwh_d) as sendout_gwh_d,
               SUM(inventory_gwh) as inventory_gwh
        FROM alsi_storage
        WHERE gas_day >= :start_date
        GROUP BY gas_day
        ORDER BY gas_day
        """
        alsi = pl.read_database(
            alsi_q.replace(":start_date", f"'{self.start_date.isoformat()}'"),
            self.engine,
        )

        if not alsi.is_empty():
            alsi = (
                alsi.lazy()
                .with_columns(pl.col("date").str.to_date(strict=False))
                .drop_nulls("date")
                .sort("date")
                .collect()
                .to_pandas()
            )
            alsi["date"] = pd.to_datetime(alsi["date"])
            alsi.rename(
                columns={
                    "sendout_gwh_d": "eu_lng_sendout_gwh_d",
                    "inventory_gwh": "eu_lng_inventory_gwh",
                },
                inplace=True,
            )
            df = df.merge(
                alsi[["date", "eu_lng_sendout_gwh_d", "eu_lng_inventory_gwh"]],
                on="date",
                how="left",
            )
            print(f"[FEATURES] Loaded ALSI: {len(alsi)} days")
        else:
            print("[FEATURES] Warning: No ALSI data found")

        return df

    def load_policy_money_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Policy-money signals: LDA lobbying filings (counts + dollars,
        energy-issue ENG activity) and House periodic transaction reports.

        Previously ingested-but-dark (lobbying 2001->, PTR 2015->).
        Event-driven and zero-inflated like congress bills, so sparse
        branch. state_bills stays out until the key activates (0 rows).
        """

        # --- Lobbying filings: daily counts + dollar flow ---
        lob_q = """
        SELECT dt_posted as date, income, expenses
        FROM lobbying_filings
        ORDER BY dt_posted
        """
        lob = pl.read_database(lob_q, self.engine)

        if not lob.is_empty():
            lob_agg = (
                lob.lazy()
                .with_columns(
                    pl.col("date").str.to_datetime(time_zone="UTC", strict=False)
                    .dt.replace_time_zone(None)
                    .dt.date(),
                    pl.col("income").cast(pl.Float64, strict=False).fill_null(0),
                    pl.col("expenses").cast(pl.Float64, strict=False).fill_null(0),
                )
                .drop_nulls("date")
                .group_by("date")
                .agg(
                    pl.len().cast(pl.Int64).alias("lobbying_filings_count"),
                    pl.col("income").sum().alias("lobbying_income"),
                    pl.col("expenses").sum().alias("lobbying_expenses"),
                )
                .sort("date")
                .collect()
                .to_pandas()
            )
            lob_agg["date"] = pd.to_datetime(lob_agg["date"])
            df = df.merge(lob_agg, on="date", how="left")
            print(
                f"[FEATURES] Loaded lobbying: {len(lob_agg)} dates, "
                f"filings={lob_agg['lobbying_filings_count'].sum():.0f}"
            )
        else:
            print("[FEATURES] Warning: No lobbying data found")

        # --- Energy-issue (ENG) lobbying activity ---
        eng_q = """
        SELECT f.dt_posted as date
        FROM lobbying_activities a
        JOIN lobbying_filings f ON a.filing_uuid = f.filing_uuid
        WHERE a.general_issue_code = 'ENG'
        """
        eng = pl.read_database(eng_q, self.engine)

        if not eng.is_empty():
            eng_agg = (
                eng.lazy()
                .with_columns(
                    pl.col("date").str.to_datetime(time_zone="UTC", strict=False)
                    .dt.replace_time_zone(None)
                    .dt.date()
                )
                .drop_nulls("date")
                .group_by("date")
                .agg(pl.len().cast(pl.Int64).alias("lobbying_energy_count"))
                .sort("date")
                .collect()
                .to_pandas()
            )
            eng_agg["date"] = pd.to_datetime(eng_agg["date"])
            df = df.merge(eng_agg, on="date", how="left")
            print(f"[FEATURES] Loaded lobbying-ENG: {len(eng_agg)} dates")
        else:
            print("[FEATURES] Warning: No lobbying-ENG activity found")

        # --- House PTR filings: daily counts ---
        ptr_q = "SELECT FilingDate as date FROM house_ptr_index"
        ptr = pl.read_database(ptr_q, self.engine)

        if not ptr.is_empty():
            ptr_agg = (
                ptr.lazy()
                .with_columns(
                    pl.coalesce(
                        pl.col("date").str.to_datetime("%m/%d/%Y", strict=False),
                        pl.col("date").str.to_datetime(strict=False),
                    )
                    .dt.date()
                    .alias("date"),
                )
                .drop_nulls("date")
                .group_by("date")
                .agg(pl.len().cast(pl.Int64).alias("house_ptr_count"))
                .sort("date")
                .collect()
                .to_pandas()
            )
            ptr_agg["date"] = pd.to_datetime(ptr_agg["date"])
            df = df.merge(ptr_agg, on="date", how="left")
            print(
                f"[FEATURES] Loaded House PTR: {len(ptr_agg)} dates, "
                f"filings={ptr_agg['house_ptr_count'].sum():.0f}"
            )
        else:
            print("[FEATURES] Warning: No House PTR data found")

        for col in [
            "lobbying_filings_count",
            "lobbying_income",
            "lobbying_expenses",
            "lobbying_energy_count",
            "house_ptr_count",
        ]:
            if col in df.columns:
                df[col] = df[col].fillna(0)

        return df

    def load_shock_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Shock-event signals: NCEI storm events (counts + damage, plus a
        grid/gas-stressor subset), FEMA disaster declarations.

        Previously ingested-but-dark (storm 2015->, 740k rows). Event-driven
        and zero-inflated, so sparse branch. Drought is intentionally left
        out: its date column holds 1970 epoch values (ingester bug) -- flag
        for the ingester, don't launder it into features.
        """

        # Grid/gas stressors: cold snaps, heat, hurricanes, high wind --
        # the events that freeze wells, spike power burn, or knock out
        # compressors (cf. Elliott Dec-2022, Texas 2021).
        SEVERE_TYPES = (
            "Winter Storm", "Winter Weather", "Blizzard", "Ice Storm",
            "Extreme Cold/Wind Chill", "Cold/Wind Chill", "Frost/Freeze",
            "Heat", "Excessive Heat", "Hurricane (Typhoon)", "Hurricane",
            "Marine Hurricane/Typhoon", "Tropical Storm",
            "Marine Tropical Storm", "High Wind",
        )

        # Polars-native scan + aggregation (reference migration: identical
        # output columns to the pandas version; boundary back to pandas for
        # the merge since the rest of the pipeline is pandas).
        storm_q = """
        SELECT DATE(begin_date) as date, event_type,
               COALESCE(property_damage, 0) as property_damage,
               COALESCE(crop_damage, 0) as crop_damage
        FROM storm_events
        WHERE DATE(begin_date) >= :start_date
        """
        storm = pl.read_database(
            storm_q.replace(":start_date", f"'{self.start_date.isoformat()}'"),
            self.engine,
        )

        if not storm.is_empty():
            storm_agg = (
                storm.lazy()
                .with_columns(
                    pl.col("date").str.to_date(strict=False),
                    pl.col("property_damage").cast(pl.Float64, strict=False),
                    pl.col("crop_damage").cast(pl.Float64, strict=False),
                )
                .drop_nulls("date")
                .with_columns(
                    pl.col("property_damage").fill_null(0),
                    pl.col("crop_damage").fill_null(0),
                )
                .group_by("date")
                .agg(
                    pl.len().cast(pl.Int64).alias("storm_event_count"),
                    pl.col("property_damage").sum().alias("storm_property_damage"),
                    pl.col("crop_damage").sum().alias("storm_crop_damage"),
                    pl.col("event_type")
                    .is_in(SEVERE_TYPES)
                    .sum()
                    .cast(pl.Int64)
                    .alias("storm_severe_count"),
                )
                .sort("date")
                .collect()
            )
            total_agg = storm_agg.to_pandas()
            total_agg["date"] = pd.to_datetime(total_agg["date"])
            df = df.merge(total_agg, on="date", how="left")
            print(
                f"[FEATURES] Loaded storms: {len(total_agg)} dates, "
                f"events={total_agg['storm_event_count'].sum():.0f}, "
                f"severe={total_agg['storm_severe_count'].sum():.0f}"
            )
        else:
            print("[FEATURES] Warning: No storm data found")

        # --- FEMA declarations: daily counts ---
        fema = pl.read_database(
            "SELECT DATE(declaration_date) as date FROM fema_disasters",
            self.engine,
        )

        if not fema.is_empty():
            fema_agg = (
                fema.lazy()
                .with_columns(pl.col("date").str.to_date(strict=False))
                .drop_nulls("date")
                .group_by("date")
                .agg(pl.len().cast(pl.Int64).alias("fema_declarations"))
                .sort("date")
                .collect()
                .to_pandas()
            )
            fema_agg["date"] = pd.to_datetime(fema_agg["date"])
            df = df.merge(fema_agg, on="date", how="left")
            print(f"[FEATURES] Loaded FEMA: {len(fema_agg)} dates")
        else:
            print("[FEATURES] Warning: No FEMA data found")

        for col in [
            "storm_event_count",
            "storm_property_damage",
            "storm_crop_damage",
            "storm_severe_count",
            "fema_declarations",
        ]:
            if col in df.columns:
                df[col] = df[col].fillna(0)

        return df

    def load_equity_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Energy-equity index: equal-weight daily log-return + breadth
        (fraction of names up) across the stock_prices universe (26 names:
        producers, majors, refiners, services, midstream, utilities, ETFs).

        Previously ingested-but-dark (ingested since 2015, never loaded).
        Requires the 2026-09-15 stock_prices cleanup (ns-epoch/NULL/micros
        formats deduped to canonical '%Y-%m-%d %H:%M:%S' text, 313k -> 151k).
        Caveat: closes splice adjusted (backfill) and unadjusted (daily)
        eras -- diluted 26x in the equal-weight mean and documented here,
        not laundered. Low-freq branch alongside CME cross-asset spreads.
        """

        eq_q = """
        SELECT DATE("timestamp") as date, "ticker", AVG("close") as close
        FROM stock_prices
        WHERE DATE("timestamp") >= :start_date
        GROUP BY DATE("timestamp"), "ticker"
        """
        eq = pl.read_database(
            eq_q.replace(":start_date", f"'{self.start_date.isoformat()}'"),
            self.engine,
        )

        if not eq.is_empty():
            daily = (
                eq.lazy()
                .with_columns(
                    pl.col("date").str.to_date(strict=False),
                    pl.col("close").cast(pl.Float64, strict=False),
                )
                .drop_nulls(["date", "close"])
                .sort(["ticker", "date"])
                .with_columns(
                    (
                        pl.col("close").log()
                        - pl.col("close").log().shift(1).over("ticker")
                    ).alias("log_ret")
                )
                .group_by("date")
                .agg(
                    pl.col("log_ret").mean().alias("eq_energy_eqw_ret"),
                    (pl.col("log_ret") > 0).mean().alias("eq_breadth_up"),
                )
                .sort("date")
                .collect()
                .to_pandas()
            )
            daily["date"] = pd.to_datetime(daily["date"])
            df = df.merge(daily, on="date", how="left")
            print(f"[FEATURES] Loaded equities: {len(daily)} days")
        else:
            print("[FEATURES] Warning: No equity data found")

        return df

    def engineer_features(self) -> pd.DataFrame:
        """Main pipeline: load all data and engineer features."""

        print(f"\n[FEATURES] Starting feature engineering pipeline (mode={METIS_MODE})")
        print(f"[FEATURES] Start date: {self.start_date}")

        # Load price data first (anchor)
        df = self.load_price_data()

        # Load all supplementary features
        df = self.load_eia_features(df)
        df = self.load_fred_features(df)
        df = self.load_bls_ppi_features(df)
        df = self.load_census_permit_features(df)
        df = self.load_congress_features(df)
        df = self.load_weather_features(df)

        # Load new energy complex features
        df = self.load_cme_futures_features(df)
        df = self.load_power_lmp_features(df)

        # Load EU gas balance (previously ingested-but-dark)
        df = self.load_eu_gas_features(df)

        # Load policy-money signals (previously ingested-but-dark)
        df = self.load_policy_money_features(df)

        # Load shock-event signals (previously ingested-but-dark)
        df = self.load_shock_features(df)

        # Load energy-equity index (previously ingested-but-dark)
        df = self.load_equity_features(df)

        # Fill missing values
        # Forward fill for lagged features, back fill for forward-looking
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        df[numeric_cols] = df[numeric_cols].fillna(method="ffill").fillna(method="bfill")

        # Remove initial rows with NaN from lagged features
        df = df.dropna(subset=["volatility_20d"])  # Requires 20 days of data

        self.df = df
        print(
            f"\n[FEATURES] Feature engineering complete: {len(df)} rows, {len(df.columns)} features"
        )
        print(f"[FEATURES] Date range: {df['date'].min()} to {df['date'].max()}")
        print(f"[FEATURES] Features: {list(df.columns)}")

        return df

    def split_features_by_frequency(self) -> dict:
        """
        Split features into 3 groups by temporal frequency.

        Returns:
            dict with 'daily', 'low_freq', 'sparse' DataFrames
        """
        if self.df is None:
            raise ValueError("Run engineer_features() first")

        df = self.df.copy()

        # Daily features: high-frequency price and volume-based
        daily_cols = [
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "log_return",
            "return_1d",
            "return_5d",
            "return_20d",
            "volatility_20d",
            "volatility_5d",
            "price_range",
            "momentum_20d",
            "volume_ma_20d",
            "volume_ratio",
        ]
        daily_features = df[[col for col in daily_cols if col in df.columns]].copy()

        # Low-frequency features: weekly, monthly, quarterly macro and structural
        low_freq_base = [
            "storage_bcf",
            "eia_storage_yoy",
            "eia_storage_change",
            "production_mmcf",
            "eia_production_change",
            "cpi_energy",
            "retail_gas_price",
            "wti_crude_price",
            "industrial_production",
            "housing_starts",
            "personal_consumption",
            "permit_count",
            "permit_6m_rolling",
            "permit_bullish",
            "permit_count_lag3m",
            "permit_bullish_lag3m",
        ]

        # Include all YoY and MA variants of low-freq features
        low_freq_cols = ["date"] + [col for col in low_freq_base if col in df.columns]
        for col in df.columns:
            if any(
                col.startswith(base) and (col.endswith("_yoy") or col.endswith("_ma"))
                for base in ["cpi_", "retail_", "wti_", "industrial_", "housing_", "personal_"]
            ):
                if col not in low_freq_cols:
                    low_freq_cols.append(col)

        # Include PPI features in low-freq
        ppi_cols = [col for col in df.columns if "ppi" in col.lower()]
        low_freq_cols.extend(ppi_cols)

        # Include CME cross-asset and LMP power-price features -- both loaders run in
        # engineer_features() and populate self.df correctly, but neither's columns were
        # ever added to any frequency group, so they were silently dropped at this exact
        # step despite being real, correctly-computed signals (confirmed during the data
        # audit). Deliberately excluding the raw natural_gas_close/volatility_20d/ma_20
        # triplet from CME: that's NG's own price from a second vendor (direct CME pull),
        # redundant with close/open already in the daily branch via ng_futures_daily --
        # including it would just duplicate near-identical price information across two
        # branches, not add cross-asset signal. The derived spreads/ratios that use it as
        # an input (ng_wti_ratio, ng_power_basis) are kept, since a spread carries
        # different information than either raw price alone.
        cross_asset_cols = [
            "crude_oil_wti_close",
            "crude_oil_wti_volatility_20d",
            "crude_oil_wti_ma_20",
            "crude_oil_brent_close",
            "crude_oil_brent_volatility_20d",
            "crude_oil_brent_ma_20",
            "heating_oil_close",
            "heating_oil_volatility_20d",
            "heating_oil_ma_20",
            "rbob_gasoline_close",
            "rbob_gasoline_volatility_20d",
            "rbob_gasoline_ma_20",
            "wti_brent_spread",
            "wti_brent_spread_pct",
            "ho_wti_crack",
            "ho_wti_spread_pct",
            "ng_wti_ratio",
        ]
        low_freq_cols.extend(
            [c for c in cross_asset_cols if c in df.columns and c not in low_freq_cols]
        )

        lmp_related_cols = [col for col in df.columns if col.startswith("lmp_")] + [
            "ng_power_basis",
            "ng_power_basis_pct",
        ]
        low_freq_cols.extend(
            [c for c in lmp_related_cols if c in df.columns and c not in low_freq_cols]
        )

        # Weather demand-forcing (NOAA CPC degree-day anomalies + hub temps).
        # Daily-resolution but fundamentally a demand-side input to the
        # storage balance, so it lives in the low-freq/fundamental branch
        # alongside EIA storage rather than the price-only daily branch.
        weather_cols = [
            "hdd_conus_dev",
            "cdd_conus_dev",
            "hdd_dev_cum_season",
            "cdd_dev_cum_season",
            "hdd_gas_conus_dev",
            "hdd_gas_dev_cum_season",
            "hdd_enc_dev_cum_season",
            "hdd_wnc_dev_cum_season",
            "hdd_conus_dev_7d",
            "cdd_conus_dev_7d",
            "temp_henry_hub",
            "temp_cushing",
        ]
        low_freq_cols.extend(
            [c for c in weather_cols if c in df.columns and c not in low_freq_cols]
        )

        # Energy-equity index -- cross-asset context like CME spreads.
        eq_cols = ["eq_energy_eqw_ret", "eq_breadth_up"]
        low_freq_cols.extend(
            [c for c in eq_cols if c in df.columns and c not in low_freq_cols]
        )

        # EU gas balance (ENTSOG flows + GIE storage/LNG) -- daily grain
        # but fundamental/supply-side, so low-freq branch like EIA storage.
        eu_cols = [
            "eu_entry_total_gwh",
            "eu_russian_share",
            "eu_storage_full_pct",
            "eu_net_withdrawal_gwh_d",
            "eu_lng_sendout_gwh_d",
            "eu_lng_inventory_gwh",
        ]
        low_freq_cols.extend(
            [c for c in eu_cols if c in df.columns and c not in low_freq_cols]
        )

        low_freq_features = df[[col for col in low_freq_cols if col in df.columns]].copy()

        # Sparse features: event-driven signals with sparse occurrence
        sparse_cols = [
            "date",
            "congress_bills_count",
            "congress_bills_energy_count",
            "congress_bills_ma",
            "congress_bills_energy_ma",
            "lobbying_filings_count",
            "lobbying_income",
            "lobbying_expenses",
            "lobbying_energy_count",
            "house_ptr_count",
            "storm_event_count",
            "storm_property_damage",
            "storm_crop_damage",
            "storm_severe_count",
            "fema_declarations",
        ]
        sparse_features = df[[col for col in sparse_cols if col in df.columns]].copy()

        return {"daily": daily_features, "low_freq": low_freq_features, "sparse": sparse_features}

    def save_features_parquet(self) -> None:
        """Save all features to parquet files (CSV for backward compatibility, parquet for frequency groups)."""
        if self.df is None:
            raise ValueError("Run engineer_features() first")

        # Save full features as CSV (backward compatibility)
        output_path_csv = os.path.join(OUTPUT_DIR, "all_features.csv")
        self.df.to_csv(output_path_csv, index=False)
        print(f"[FEATURES] Saved full features (CSV): {output_path_csv}")

        # Split by frequency and save as parquet
        features_split = self.split_features_by_frequency()

        for freq_name, freq_df in features_split.items():
            output_path_parquet = os.path.join(OUTPUT_DIR, f"{freq_name}_features.parquet")
            freq_df.to_parquet(output_path_parquet, index=False, compression="snappy")
            print(
                f"[FEATURES] Saved {freq_name} features ({len(freq_df.columns)} cols): {output_path_parquet}"
            )

    def save_features(self, filename: str = "all_features.csv") -> str:
        """Save features to CSV."""
        if self.df is None:
            raise ValueError("Run engineer_features() first")

        output_path = os.path.join(OUTPUT_DIR, filename)
        self.df.to_csv(output_path, index=False)

        print(f"\n[FEATURES] Saved to {output_path}")
        print(f"[FEATURES] Shape: {self.df.shape}")
        print(f"[FEATURES] Missing values:\n{self.df.isnull().sum()}")

        return output_path

    def get_training_data(self, test_size: float = 0.2, holdout_months: int = 6):
        """
        Split data for training, validation, and test.

        Args:
            test_size: Proportion for test set
            holdout_months: Months to holdout from training for validation

        Returns:
            dict with 'train', 'val', 'test' DataFrames
        """
        if self.df is None:
            raise ValueError("Run engineer_features() first")

        df = self.df.copy()

        # Chronological split
        n = len(df)
        test_start_idx = int(n * (1 - test_size))
        val_start_idx = test_start_idx - int(
            holdout_months * 252 / 365
        )  # ~holdout_months of trading days

        train = df[:val_start_idx]
        val = df[val_start_idx:test_start_idx]
        test = df[test_start_idx:]

        print(f"\n[FEATURES] Train/Val/Test split:")
        print(f"  Train: {len(train)} rows ({train['date'].min()} to {train['date'].max()})")
        print(f"  Val:   {len(val)} rows ({val['date'].min()} to {val['date'].max()})")
        print(f"  Test:  {len(test)} rows ({test['date'].min()} to {test['date'].max()})")

        return {"train": train, "val": val, "test": test}


if __name__ == "__main__":
    engineer = FeatureEngineer(DB_URL, start_date="2015-01-01")
    df = engineer.engineer_features()

    # Save full features (CSV) and frequency-split features (parquet)
    engineer.save_features()
    engineer.save_features_parquet()

    # Also save train/val/test splits (CSV for backward compatibility)
    splits = engineer.get_training_data(test_size=0.15, holdout_months=6)
    splits["train"].to_csv(os.path.join(OUTPUT_DIR, "train_features.csv"), index=False)
    splits["val"].to_csv(os.path.join(OUTPUT_DIR, "val_features.csv"), index=False)
    splits["test"].to_csv(os.path.join(OUTPUT_DIR, "test_features.csv"), index=False)

    # Save frequency-split train/val/test as parquet files
    features_split = engineer.split_features_by_frequency()
    for freq_name, freq_df in features_split.items():
        freq_train = freq_df[: len(splits["train"])]
        freq_val = freq_df[len(splits["train"]) : len(splits["train"]) + len(splits["val"])]
        freq_test = freq_df[len(splits["train"]) + len(splits["val"]) :]

        freq_train.to_parquet(
            os.path.join(OUTPUT_DIR, f"train_{freq_name}_features.parquet"),
            index=False,
            compression="zstd",
        )
        freq_val.to_parquet(
            os.path.join(OUTPUT_DIR, f"val_{freq_name}_features.parquet"),
            index=False,
            compression="zstd",
        )
        freq_test.to_parquet(
            os.path.join(OUTPUT_DIR, f"test_{freq_name}_features.parquet"),
            index=False,
            compression="zstd",
        )

        print(f"[FEATURES] Saved {freq_name} train/val/test splits (parquet)")

    print(f"\n[FEATURES] Saved train/val/test splits to {OUTPUT_DIR}")
    print("[SUCCESS] Feature engineering complete!")
