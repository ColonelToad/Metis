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
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import warnings
warnings.filterwarnings('ignore')

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
        """Load NG futures price data and calculate price-based features."""
        query = """
        SELECT date, open, high, low, close, volume
        FROM ng_futures_daily
        WHERE date >= :start_date
        ORDER BY date
        """
        
        with self.engine.connect() as conn:
            df = pd.read_sql(
                text(query),
                conn,
                params={"start_date": self.start_date.isoformat()}
            )
        
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        
        # Log returns
        df['log_return'] = np.log(df['close'] / df['close'].shift(1))
        df['return_1d'] = df['log_return']
        df['return_5d'] = df['log_return'].rolling(5).sum().shift(1)
        df['return_20d'] = df['log_return'].rolling(20).sum().shift(1)
        
        # Volatility (annualized)
        df['volatility_20d'] = df['log_return'].rolling(20).std() * np.sqrt(252)
        df['volatility_5d'] = df['log_return'].rolling(5).std() * np.sqrt(252)
        
        # Price range and momentum
        df['price_range'] = (df['high'] - df['low']) / df['close']
        df['momentum_20d'] = (df['close'] - df['close'].shift(20)) / df['close'].shift(20)
        
        # Volume trend
        df['volume_ma_20d'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / (df['volume_ma_20d'] + 1e-8)
        
        print(f"[FEATURES] Loaded {len(df)} price records from {df['date'].min()} to {df['date'].max()}")
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
        
        with self.engine.connect() as conn:
            eia_storage = pd.read_sql(
                text(query_storage),
                conn,
                params={"start_date": self.start_date.isoformat()}
            )
        
        if not eia_storage.empty:
            eia_storage['date'] = pd.to_datetime(eia_storage['date'])
            eia_storage['storage_bcf'] = pd.to_numeric(eia_storage['storage_bcf'], errors='coerce')
            eia_storage['eia_storage_yoy'] = eia_storage['storage_bcf'].pct_change(52)  # 1 year = ~52 weeks
            eia_storage['eia_storage_change'] = eia_storage['storage_bcf'].diff()
            
            # Merge to main dataframe using forward fill (weekly data to daily)
            df = df.merge(eia_storage[['date', 'storage_bcf', 'eia_storage_yoy', 'eia_storage_change']], 
                          on='date', how='left')
            df['storage_bcf'] = df['storage_bcf'].fillna(method='ffill')
            df['eia_storage_yoy'] = df['eia_storage_yoy'].fillna(method='ffill')
            df['eia_storage_change'] = df['eia_storage_change'].fillna(method='ffill')
            
            print(f"[FEATURES] Loaded EIA storage data: {eia_storage['date'].min()} to {eia_storage['date'].max()}")
        else:
            print("[FEATURES] Warning: No EIA storage data found")
        
        # EIA Production
        query_prod = """
        SELECT timestamp as date, production_mmcf
        FROM eia_production
        WHERE timestamp >= :start_date
        ORDER BY timestamp
        """
        
        with self.engine.connect() as conn:
            eia_prod = pd.read_sql(
                text(query_prod),
                conn,
                params={"start_date": self.start_date.isoformat()}
            )
        
        if not eia_prod.empty:
            eia_prod['date'] = pd.to_datetime(eia_prod['date'])
            eia_prod['production_mmcf'] = pd.to_numeric(eia_prod['production_mmcf'], errors='coerce')
            eia_prod['eia_production_yoy'] = eia_prod['production_mmcf'].pct_change(52)
            eia_prod['eia_production_change'] = eia_prod['production_mmcf'].diff()
            
            df = df.merge(eia_prod[['date', 'production_mmcf', 'eia_production_yoy', 'eia_production_change']], 
                          on='date', how='left')
            df['production_mmcf'] = df['production_mmcf'].fillna(method='ffill')
            df['eia_production_yoy'] = df['eia_production_yoy'].fillna(method='ffill')
            df['eia_production_change'] = df['eia_production_change'].fillna(method='ffill')
            
            print(f"[FEATURES] Loaded EIA production data: {eia_prod['date'].min()} to {eia_prod['date'].max()}")
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
        
        with self.engine.connect() as conn:
            fred = pd.read_sql(
                text(query),
                conn,
                params={"start_date": self.start_date.isoformat()}
            )
        
        if not fred.empty:
            fred['date'] = pd.to_datetime(fred['date'])
            
            # Convert numeric columns
            for col in fred.columns:
                if col != 'date':
                    fred[col] = pd.to_numeric(fred[col], errors='coerce')
            
            # Forward fill base columns first (sparse FRED data)
            base_cols = [col for col in fred.columns if col != 'date']
            for col in base_cols:
                fred[col] = fred[col].fillna(method='ffill').fillna(method='bfill')
            
            # Calculate YoY changes for each indicator (4 quarters for FRED monthly/quarterly)
            derived_cols = []
            for col in base_cols:
                fred[f'{col}_yoy'] = fred[col].pct_change(4)  # 4 quarters
                fred[f'{col}_ma'] = fred[col].rolling(4).mean()  # 4-period MA
                derived_cols.extend([f'{col}_yoy', f'{col}_ma'])
            
            df = df.merge(fred, on='date', how='left')
            
            # Forward fill ALL FRED columns (base + derived) to daily data
            all_fred_cols = base_cols + derived_cols
            for col in all_fred_cols:
                if col in df.columns:
                    df[col] = df[col].fillna(method='ffill').fillna(method='bfill')
            
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
        
        with self.engine.connect() as conn:
            ppi = pd.read_sql(
                text(query),
                conn,
                params={"start_date": self.start_date.isoformat()}
            )
        
        if not ppi.empty:
            # NOTE: bls_ppi.date carries ingestion-time timestamps (sub-second precision),
            # not normalized calendar dates. An exact-date merge against ng_futures_daily
            # (midnight-normalized) previously matched zero rows for every PPI series,
            # silently producing 100%-NaN columns. Normalize first, then use merge_asof
            # (nearest prior date) rather than exact match, since PPI is monthly data and
            # an exact join still fails whenever the 1st of the month isn't a trading day.
            ppi['date'] = pd.to_datetime(ppi['date']).dt.normalize()
            ppi = ppi.sort_values('date')
            df = df.sort_values('date')
            
            # Pivot to get each series as a column
            # For each series: take the PPI index and YoY change
            for series_id in ppi['series_id'].unique():
                series_data = ppi[ppi['series_id'] == series_id][['date', 'ppi_index', 'ppi_yoy_change']].copy()
                series_data.columns = ['date', f'ppi_index_{series_id}', f'ppi_yoy_{series_id}']
                series_data = series_data.sort_values('date')
                df = pd.merge_asof(df, series_data, on='date', direction='backward')
            
            # Simple aggregate: average PPI across energy series
            ppi_cols = [c for c in df.columns if c.startswith('ppi_index_')]
            if ppi_cols:
                df['ppi_energy_avg'] = df[ppi_cols].mean(axis=1)
                
                # YoY aggregate
                ppi_yoy_cols = [c for c in df.columns if c.startswith('ppi_yoy_')]
                if ppi_yoy_cols:
                    df['ppi_yoy_avg'] = df[ppi_yoy_cols].mean(axis=1)
            
            n_populated = df[ppi_cols[0]].notna().sum() if ppi_cols else 0
            print(f"[FEATURES] Loaded BLS PPI data ({len(ppi['series_id'].unique())} series, "
                  f"{n_populated}/{len(df)} rows populated post-merge_asof)")
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
        
        with self.engine.connect() as conn:
            permits = pd.read_sql(
                text(query),
                conn,
                params={"start_date": self.start_date.isoformat()}
            )
        
        if not permits.empty:
            permits['date'] = pd.to_datetime(permits['date'])
            permits = permits[[
                'date', 'permit_count', 'permit_6m_rolling', 
                'permit_yoy_change', 'permit_bullish'
            ]]
            
            df = df.merge(permits, on='date', how='left')
            
            # Forward-looking signal: permits lead construction by ~3-6 months
            # Create lagged features to capture lead relationship
            df['permit_count_lag3m'] = df['permit_count'].shift(3)
            df['permit_bullish_lag3m'] = df['permit_bullish'].shift(3)
            
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
        
        with self.engine.connect() as conn:
            congress = pd.read_sql(
                text(query),
                conn,
                params={"start_date": self.start_date.isoformat()}
            )
        
        if not congress.empty:
            congress['date'] = pd.to_datetime(congress['date'], errors='coerce', utc=True).dt.tz_convert(None)
            congress['is_energy_related'] = pd.to_numeric(congress['is_energy_related'], errors='coerce').fillna(0).astype(int)
            
            total_agg = congress.groupby('date').size().reset_index(name='congress_bills_count')
            energy_agg = (congress[congress['is_energy_related'] == 1]
                          .groupby('date')
                          .size()
                          .reset_index(name='congress_bills_energy_count'))
            
            df = df.merge(total_agg, on='date', how='left')
            df = df.merge(energy_agg, on='date', how='left')
            df['congress_bills_count'] = df['congress_bills_count'].fillna(0)
            df['congress_bills_energy_count'] = df['congress_bills_energy_count'].fillna(0)
            
            df['congress_bills_ma'] = df['congress_bills_count'].rolling(20).mean()
            df['congress_bills_energy_ma'] = df['congress_bills_energy_count'].rolling(20).mean()
            
            print(f"[FEATURES] Loaded Congress bills: {len(total_agg)} dates, total={total_agg['congress_bills_count'].sum():.0f}, energy={energy_agg['congress_bills_energy_count'].sum():.0f}")
        else:
            print("[FEATURES] Warning: No Congress data found")
        
        return df
    
    def load_cme_futures_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Load CME futures data (WTI, Brent, HO, RB) from cme_futures_daily table."""
        
        query = """
        SELECT date, contract_type, close, volatility_20d, ma_20
        FROM cme_futures_daily
        WHERE date >= :start_date
        ORDER BY date
        """
        
        with self.engine.connect() as conn:
            cme = pd.read_sql(
                text(query),
                conn,
                params={"start_date": self.start_date.isoformat()}
            )
        
        if not cme.empty:
            cme['date'] = pd.to_datetime(cme['date'], format="ISO8601").dt.normalize()
            
            # NOTE: cme_futures_daily carries duplicate rows per (date, contract_type) --
            # confirmed identical values under two different timestamp serializations,
            # same class of bug as the bls_ppi fix above, but hitting all 5 tracked
            # contracts rather than one series. Left unguarded, a plain merge fans out
            # 2x per contract, compounding to 2^5=32x across the 5 sequential merges below.
            n_before = len(cme)
            cme = cme.drop_duplicates(subset=['date', 'contract_type'], keep='first')
            n_after = len(cme)
            if n_after < n_before:
                print(f"[FEATURES] Deduped cme_futures_daily: {n_before} -> {n_after} rows")
            
            # Pivot contracts to get separate columns
            for contract in cme['contract_type'].unique():
                contract_data = cme[cme['contract_type'] == contract][['date', 'close', 'volatility_20d', 'ma_20']]
                contract_data.columns = ['date', f'{contract}_close', f'{contract}_volatility_20d', f'{contract}_ma_20']
                
                # Merge to main dataframe
                df = df.merge(contract_data, on='date', how='left')
            
            # Calculate cross-asset spreads
            if 'crude_oil_wti_close' in df.columns and 'crude_oil_brent_close' in df.columns:
                df['wti_brent_spread'] = df['crude_oil_wti_close'] - df['crude_oil_brent_close']
                df['wti_brent_spread_pct'] = (df['wti_brent_spread'] / df['crude_oil_brent_close'] * 100).fillna(0)
            
            # HO-WTI crack spread (heating oil relative to WTI)
            if 'heating_oil_close' in df.columns and 'crude_oil_wti_close' in df.columns:
                df['ho_wti_crack'] = df['heating_oil_close'] - (df['crude_oil_wti_close'] * 0.42)  # Rough conversion
                df['ho_wti_spread_pct'] = (df['ho_wti_crack'] / (df['crude_oil_wti_close'] * 0.42) * 100).fillna(0)
            
            # NG correlation to crude (lead/lag to be analyzed separately)
            if 'natural_gas_close' in df.columns and 'crude_oil_wti_close' in df.columns:
                df['ng_wti_ratio'] = df['natural_gas_close'] / (df['crude_oil_wti_close'] + 1e-8)
            
            print(f"[FEATURES] Loaded CME futures data ({len(cme['contract_type'].unique())} contracts)")
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
        
        with self.engine.connect() as conn:
            lmp = pd.read_sql(
                text(query),
                conn,
                params={"start_date": self.start_date.isoformat()}
            )
        
        if not lmp.empty:
            lmp['date'] = pd.to_datetime(lmp['date']).dt.normalize()
            
            # Same class of duplicate-row risk as cme_futures_daily -- guard even though
            # the GROUP BY in the query above already aggregates within a calendar day;
            # this only protects against a second, differently-timestamped write of the
            # same (date, iso) slipping through as a distinct group.
            n_before = len(lmp)
            lmp = lmp.drop_duplicates(subset=['date', 'iso'], keep='first')
            n_after = len(lmp)
            if n_after < n_before:
                print(f"[FEATURES] Deduped grid_lmp_multi_iso: {n_before} -> {n_after} rows")
            
            # Pivot ISOs to separate columns
            for iso in lmp['iso'].unique():
                iso_data = lmp[lmp['iso'] == iso][['date', 'lmp_avg']]
                iso_data.columns = ['date', f'lmp_{iso.lower()}_avg']
                df = df.merge(iso_data, on='date', how='left')
            
            # Calculate composite LMP index (equal-weighted across ISOs)
            lmp_cols = [col for col in df.columns if col.startswith('lmp_') and col.endswith('_avg')]
            if lmp_cols:
                df['lmp_composite_avg'] = df[lmp_cols].mean(axis=1)
                df['lmp_composite_std'] = df[lmp_cols].std(axis=1)
                df['lmp_composite_max'] = df[lmp_cols].max(axis=1)
                df['lmp_composite_min'] = df[lmp_cols].min(axis=1)
            
            # NG-to-power basis: how much more expensive is power relative to NG fuel value
            # Rough: LMP should correlate to NG price; basis = LMP - (NG_price * conversion_factor)
            if 'natural_gas_close' in df.columns and 'lmp_composite_avg' in df.columns:
                # Power generation efficiency: ~1 MMBtu of gas -> ~1 MWh with losses
                # LMP in $/MWh, NG in $/MMBtu, so direct comparison with efficiency factor
                df['ng_power_basis'] = df['lmp_composite_avg'] - (df['natural_gas_close'] * 10)  # 10x factor for scale
                df['ng_power_basis_pct'] = (df['ng_power_basis'] / (df['natural_gas_close'] * 10 + 1e-8) * 100).fillna(0)
            
            print(f"[FEATURES] Loaded LMP data ({len(lmp['iso'].unique())} ISOs)")
        else:
            print("[FEATURES] Warning: No LMP data found")
        
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
        
        # Load new energy complex features
        df = self.load_cme_futures_features(df)
        df = self.load_power_lmp_features(df)
        
        # Fill missing values
        # Forward fill for lagged features, back fill for forward-looking
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        df[numeric_cols] = df[numeric_cols].fillna(method='ffill').fillna(method='bfill')
        
        # Remove initial rows with NaN from lagged features
        df = df.dropna(subset=['volatility_20d'])  # Requires 20 days of data
        
        self.df = df
        print(f"\n[FEATURES] Feature engineering complete: {len(df)} rows, {len(df.columns)} features")
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
            'date', 'open', 'high', 'low', 'close', 'volume',
            'log_return', 'return_1d', 'return_5d', 'return_20d',
            'volatility_20d', 'volatility_5d', 'price_range', 
            'momentum_20d', 'volume_ma_20d', 'volume_ratio'
        ]
        daily_features = df[[col for col in daily_cols if col in df.columns]].copy()
        
        # Low-frequency features: weekly, monthly, quarterly macro and structural
        low_freq_base = [
            'storage_bcf', 'eia_storage_yoy', 'eia_storage_change',
            'production_mmcf', 'eia_production_change',
            'cpi_energy', 'retail_gas_price', 'wti_crude_price',
            'industrial_production', 'housing_starts', 'personal_consumption',
            'permit_count', 'permit_6m_rolling', 'permit_bullish',
            'permit_count_lag3m', 'permit_bullish_lag3m'
        ]
        
        # Include all YoY and MA variants of low-freq features
        low_freq_cols = ['date'] + [col for col in low_freq_base if col in df.columns]
        for col in df.columns:
            if any(col.startswith(base) and (col.endswith('_yoy') or col.endswith('_ma')) 
                   for base in ['cpi_', 'retail_', 'wti_', 'industrial_', 'housing_', 'personal_']):
                if col not in low_freq_cols:
                    low_freq_cols.append(col)
        
        # Include PPI features in low-freq
        ppi_cols = [col for col in df.columns if 'ppi' in col.lower()]
        low_freq_cols.extend(ppi_cols)
        
        low_freq_features = df[[col for col in low_freq_cols if col in df.columns]].copy()
        
        # Sparse features: event-driven signals with sparse occurrence
        sparse_cols = ['date', 'congress_bills_count', 'congress_bills_energy_count', 
                       'congress_bills_ma', 'congress_bills_energy_ma']
        sparse_features = df[[col for col in sparse_cols if col in df.columns]].copy()
        
        return {
            'daily': daily_features,
            'low_freq': low_freq_features,
            'sparse': sparse_features
        }
    
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
            freq_df.to_parquet(output_path_parquet, index=False, compression='snappy')
            print(f"[FEATURES] Saved {freq_name} features ({len(freq_df.columns)} cols): {output_path_parquet}")
    
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
        val_start_idx = test_start_idx - int(holdout_months * 252 / 365)  # ~holdout_months of trading days
        
        train = df[:val_start_idx]
        val = df[val_start_idx:test_start_idx]
        test = df[test_start_idx:]
        
        print(f"\n[FEATURES] Train/Val/Test split:")
        print(f"  Train: {len(train)} rows ({train['date'].min()} to {train['date'].max()})")
        print(f"  Val:   {len(val)} rows ({val['date'].min()} to {val['date'].max()})")
        print(f"  Test:  {len(test)} rows ({test['date'].min()} to {test['date'].max()})")
        
        return {'train': train, 'val': val, 'test': test}


if __name__ == "__main__":
    engineer = FeatureEngineer(DB_URL, start_date="2015-01-01")
    df = engineer.engineer_features()
    
    # Save full features (CSV) and frequency-split features (parquet)
    engineer.save_features()
    engineer.save_features_parquet()
    
    # Also save train/val/test splits (CSV for backward compatibility)
    splits = engineer.get_training_data(test_size=0.15, holdout_months=6)
    splits['train'].to_csv(os.path.join(OUTPUT_DIR, "train_features.csv"), index=False)
    splits['val'].to_csv(os.path.join(OUTPUT_DIR, "val_features.csv"), index=False)
    splits['test'].to_csv(os.path.join(OUTPUT_DIR, "test_features.csv"), index=False)
    
    # Save frequency-split train/val/test as parquet files
    features_split = engineer.split_features_by_frequency()
    for freq_name, freq_df in features_split.items():
        freq_train = freq_df[:len(splits['train'])]
        freq_val = freq_df[len(splits['train']):len(splits['train'])+len(splits['val'])]
        freq_test = freq_df[len(splits['train'])+len(splits['val']):]
        
        freq_train.to_parquet(os.path.join(OUTPUT_DIR, f"train_{freq_name}_features.parquet"), index=False, compression='zstd')
        freq_val.to_parquet(os.path.join(OUTPUT_DIR, f"val_{freq_name}_features.parquet"), index=False, compression='zstd')
        freq_test.to_parquet(os.path.join(OUTPUT_DIR, f"test_{freq_name}_features.parquet"), index=False, compression='zstd')
        
        print(f"[FEATURES] Saved {freq_name} train/val/test splits (parquet)")
    
    print(f"\n[FEATURES] Saved train/val/test splits to {OUTPUT_DIR}")
    print("[SUCCESS] Feature engineering complete!")
