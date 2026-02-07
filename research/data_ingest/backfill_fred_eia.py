#!/usr/bin/env python3
"""
Backfill historical FRED and EIA data from 2015 to present.

This script:
1. Fetches FRED series back to 2015-01-01
2. Fetches EIA storage and production data back to 2015-01-01  
3. Inserts into existing database with proper error handling
4. Preserves existing timestamps column for compatibility
"""

import os
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from dotenv import load_dotenv
import requests
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
FRED_API_KEY = os.getenv('FRED_API_KEY')
EIA_API_KEY = os.getenv('EIA_API_KEY')

DB_PATH = 'data/metis.db'
START_DATE = '2015-01-01'
END_DATE = datetime.now().strftime('%Y-%m-%d')

# FRED series IDs for NG macro indicators
FRED_SERIES = {
    'unemployment_rate': 'UNRATE',
    'cpi_energy': 'CPILEGSL',
    'retail_gas_price': 'GASREGCOVW',
    'wti_crude_price': 'DCOILWTICO',
    'industrial_production': 'INDPRO',
    'housing_starts': 'HOUST',
    'personal_consumption': 'PCE'
}

class FREDBackfiller:
    """Fetch historical FRED data."""
    
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = 'https://api.stlouisfed.org/fred/series/observations'
        
    def fetch_series(self, series_id, start_date, end_date):
        """Fetch single FRED series."""
        params = {
            'series_id': series_id,
            'api_key': self.api_key,
            'file_type': 'json',
            'observation_start': start_date,
            'observation_end': end_date
        }
        
        try:
            logger.info(f"Fetching FRED {series_id}...")
            response = requests.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            if 'observations' not in data:
                logger.warning(f"No data for {series_id}")
                return pd.DataFrame()
                
            obs = data['observations']
            df = pd.DataFrame(obs)
            
            # Parse date and value
            df['date'] = pd.to_datetime(df['date'])
            df['value'] = pd.to_numeric(df['value'], errors='coerce')
            
            # Filter out missing values
            df = df[df['value'].notna()].copy()
            
            if len(df) > 0:
                logger.info(f"  Found {len(df)} observations: {df['date'].min()} to {df['date'].max()}")
            
            return df[['date', 'value']]
            
        except Exception as e:
            logger.error(f"Error fetching {series_id}: {e}")
            return pd.DataFrame()
    
    def fetch_all(self):
        """Fetch all FRED series and combine."""
        all_data = {}
        
        for col_name, series_id in FRED_SERIES.items():
            df = self.fetch_series(series_id, START_DATE, END_DATE)
            if not df.empty:
                df.rename(columns={'value': col_name}, inplace=True)
                all_data[col_name] = df
        
        if not all_data:
            logger.error("No FRED data fetched")
            return pd.DataFrame()
        
        # Combine all series on date
        result = list(all_data.values())[0][['date', list(all_data.keys())[0]]]
        
        for col_name in list(all_data.keys())[1:]:
            df = all_data[col_name]
            result = result.merge(df, on='date', how='outer')
        
        result = result.sort_values('date')
        
        logger.info(f"Combined FRED: {len(result)} rows, {result['date'].min()} to {result['date'].max()}")
        
        return result

class EIABackfiller:
    """Fetch historical EIA data."""
    
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = 'https://api.eia.gov/v2'
        
    def fetch_storage(self):
        """Fetch EIA Natural Gas Storage data."""
        try:
            logger.info("Fetching EIA storage data...")
            
            # EIA Natural Gas Storage - use direct download URL instead of API
            # Get weekly storage data from EIA
            url = "https://www.eia.gov/dnav/ng/hist/rngwhhd.txt"
            
            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                
                records = []
                lines = response.text.strip().split('\n')
                
                # Skip header lines, data starts after description
                skip_header = True
                for line in lines:
                    if skip_header:
                        if line.strip() and line[0:4].isdigit():
                            skip_header = False
                        else:
                            continue
                    
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            date_str = parts[0]
                            value_str = parts[1]
                            
                            # Parse date
                            year, month, day = date_str.split('-')
                            date = datetime(int(year), int(month), int(day)).date()
                            
                            if date >= datetime.strptime(START_DATE, '%Y-%m-%d').date():
                                value = float(value_str) if value_str != 'NA' else None
                                records.append({'date': date, 'storage_bcf': value})
                        except (ValueError, IndexError):
                            continue
                
                if records:
                    df = pd.DataFrame(records)
                    df['date'] = pd.to_datetime(df['date'])
                    logger.info(f"  Found {len(df)} storage observations: {df['date'].min()} to {df['date'].max()}")
                    return df
                    
            except Exception as e:
                logger.warning(f"Could not fetch EIA storage via direct URL: {e}, will skip")
            
            return pd.DataFrame()
            
        except Exception as e:
            logger.error(f"Error fetching EIA storage: {e}")
            return pd.DataFrame()
    
    def fetch_production(self):
        """Fetch EIA Natural Gas Production data."""
        try:
            logger.info("Fetching EIA production data...")
            
            # EIA Natural Gas Production (monthly) - direct download
            url = "https://www.eia.gov/dnav/ng/hist/rngp1a2m.txt"
            
            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                
                records = []
                lines = response.text.strip().split('\n')
                
                # Skip header lines, data starts after description
                skip_header = True
                for line in lines:
                    if skip_header:
                        if line.strip() and line[0:4].isdigit():
                            skip_header = False
                        else:
                            continue
                    
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            date_str = parts[0]
                            value_str = parts[1]
                            
                            # Parse date (YYYY-MM format in the file)
                            year, month = date_str.split('-')[0:2]
                            date = datetime(int(year), int(month), 1).date()
                            
                            if date >= datetime.strptime(START_DATE, '%Y-%m-%d').date():
                                value = float(value_str) if value_str != 'NA' else None
                                records.append({'date': date, 'production_mmcf': value})
                        except (ValueError, IndexError):
                            continue
                
                if records:
                    df = pd.DataFrame(records)
                    df['date'] = pd.to_datetime(df['date'])
                    logger.info(f"  Found {len(df)} production observations: {df['date'].min()} to {df['date'].max()}")
                    return df
                    
            except Exception as e:
                logger.warning(f"Could not fetch EIA production via direct URL: {e}, will skip")
            
            return pd.DataFrame()
            
        except Exception as e:
            logger.error(f"Error fetching EIA production: {e}")
            return pd.DataFrame()

def insert_fred_data(df, db_path):
    """Insert FRED data into database, updating existing records."""
    if df.empty:
        logger.warning("No FRED data to insert")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Convert date to ISO string format for SQLite datetime
        df['timestamp'] = df['date'].dt.strftime('%Y-%m-%d')
        
        # Delete existing records in our date range to avoid duplicates
        min_date = df['date'].min().strftime('%Y-%m-%d')
        max_date = df['date'].max().strftime('%Y-%m-%d')
        
        cursor.execute(
            "DELETE FROM fred_macro WHERE timestamp >= ? AND timestamp <= ?",
            (min_date, max_date)
        )
        logger.info(f"Deleted existing FRED records from {min_date} to {max_date}")
        
        # Insert new records
        cols = [c for c in df.columns if c not in ['date', 'timestamp']]
        for _, row in df.iterrows():
            values = [row['timestamp']] + [row[col] for col in cols]
            placeholders = ','.join(['?' for _ in range(len(values))])
            sql = f"INSERT INTO fred_macro (timestamp, {','.join(cols)}) VALUES ({placeholders})"
            cursor.execute(sql, values)
        
        conn.commit()
        logger.info(f"Inserted {len(df)} FRED records into database")
        
    except Exception as e:
        logger.error(f"Error inserting FRED data: {e}")
        conn.rollback()
    finally:
        conn.close()

def insert_eia_storage(df, db_path):
    """Insert EIA storage data into database."""
    if df.empty:
        logger.warning("No EIA storage data to insert")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        df['timestamp'] = df['date'].dt.strftime('%Y-%m-%d')
        
        # Delete existing records
        min_date = df['date'].min().strftime('%Y-%m-%d')
        max_date = df['date'].max().strftime('%Y-%m-%d')
        
        cursor.execute(
            "DELETE FROM eia_storage WHERE timestamp >= ? AND timestamp <= ?",
            (min_date, max_date)
        )
        logger.info(f"Deleted existing EIA storage records from {min_date} to {max_date}")
        
        # Insert new records
        for _, row in df.iterrows():
            cursor.execute(
                "INSERT INTO eia_storage (timestamp, storage_bcf) VALUES (?, ?)",
                (row['timestamp'], row['storage_bcf'])
            )
        
        conn.commit()
        logger.info(f"Inserted {len(df)} EIA storage records into database")
        
    except Exception as e:
        logger.error(f"Error inserting EIA storage data: {e}")
        conn.rollback()
    finally:
        conn.close()

def insert_eia_production(df, db_path):
    """Insert EIA production data into database."""
    if df.empty:
        logger.warning("No EIA production data to insert")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        df['timestamp'] = df['date'].dt.strftime('%Y-%m-%d')
        
        # Delete existing records
        min_date = df['date'].min().strftime('%Y-%m-%d')
        max_date = df['date'].max().strftime('%Y-%m-%d')
        
        cursor.execute(
            "DELETE FROM eia_production WHERE timestamp >= ? AND timestamp <= ?",
            (min_date, max_date)
        )
        logger.info(f"Deleted existing EIA production records from {min_date} to {max_date}")
        
        # Insert new records
        for _, row in df.iterrows():
            cursor.execute(
                "INSERT INTO eia_production (timestamp, production_mmcf) VALUES (?, ?)",
                (row['timestamp'], row['production_mmcf'])
            )
        
        conn.commit()
        logger.info(f"Inserted {len(df)} EIA production records into database")
        
    except Exception as e:
        logger.error(f"Error inserting EIA production data: {e}")
        conn.rollback()
    finally:
        conn.close()

def main():
    """Run backfill."""
    logger.info("=" * 60)
    logger.info("Starting historical data backfill (2015-present)")
    logger.info("=" * 60)
    
    # Validate API keys
    if not FRED_API_KEY:
        logger.error("FRED_API_KEY not set in .env")
        return
    if not EIA_API_KEY:
        logger.error("EIA_API_KEY not set in .env")
        return
    
    # Fetch FRED data
    fred_backfiller = FREDBackfiller(FRED_API_KEY)
    fred_df = fred_backfiller.fetch_all()
    
    if not fred_df.empty:
        insert_fred_data(fred_df, DB_PATH)
    
    # Fetch EIA data
    eia_backfiller = EIABackfiller(EIA_API_KEY)
    
    storage_df = eia_backfiller.fetch_storage()
    if not storage_df.empty:
        insert_eia_storage(storage_df, DB_PATH)
    
    production_df = eia_backfiller.fetch_production()
    if not production_df.empty:
        insert_eia_production(production_df, DB_PATH)
    
    logger.info("=" * 60)
    logger.info("Backfill complete!")
    logger.info("=" * 60)

if __name__ == '__main__':
    main()
