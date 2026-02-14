"""
EIA Jet Fuel Production and Inventory Data Ingestion

Captures aviation fuel supply-side metrics:
- Jet fuel production (thousand barrels per day)
- Jet fuel inventory (million barrels)
- Calculated: weeks of supply, YoY change %

Complements aviation_fuel table (which tracks airline demand via consumption).
Together: consumption + production = demand/supply gap = supply constraint signal.
"""

import os
import sys
from pathlib import Path
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine
import logging

# Add parent directory (research/) to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))
from common import runtime_config as rc

logger = logging.getLogger(__name__)

load_dotenv()
EIA_API_KEY = os.getenv("EIA_API_KEY")
DB_URL = rc.get_db_url()


def fetch_jet_fuel_production():
    """
    Fetch jet fuel production data from EIA API.
    
    Endpoint: Petroleum Data - Refiner Net Input of Crude Oil and Petroleum Products
    Series includes: Jet Fuel Production (US aggregate)
    Frequency: Weekly average
    """
    if not rc.require_real_mode("EIA jet fuel production API"):
        logger.info("DEV mode: skipping EIA jet fuel production API call")
        return pd.DataFrame()
    
    if not EIA_API_KEY:
        logger.warning("EIA_API_KEY not set. Skipping jet fuel production fetch.")
        return pd.DataFrame()
    
    try:
        # EIA API v2 endpoint for petroleum data
        url = "https://api.eia.gov/v2/petroleum/prf/prf_ofdsw/data/"
        
        params = {
            "api_key": EIA_API_KEY,
            "frequency": "weekly",
            "data[0]": "value",
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": 500
        }
        
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        if 'response' not in data or 'data' not in data['response']:
            logger.warning("Unexpected EIA API response structure")
            return pd.DataFrame()
        
        df = pd.DataFrame(data['response']['data'])
        
        if df.empty:
            logger.warning("No jet fuel production data returned from EIA API")
            return pd.DataFrame()
        
        # Normalize timestamp column
        df['timestamp'] = pd.to_datetime(df['period'])
        df = df.rename(columns={'value': 'production_thousand_bpd'})
        
        # Convert to numeric, drop nulls
        df['production_thousand_bpd'] = pd.to_numeric(df['production_thousand_bpd'], errors='coerce')
        df = df.dropna(subset=['production_thousand_bpd'])
        
        # Select relevant columns
        df = df[['timestamp', 'production_thousand_bpd']]
        df = df.sort_values('timestamp')
        
        logger.info(f"Fetched {len(df)} jet fuel production records")
        logger.info(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
        
        return df
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching jet fuel production: {e}")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Unexpected error in jet fuel production fetch: {e}")
        return pd.DataFrame()


def fetch_jet_fuel_inventory():
    """
    Fetch jet fuel inventory data from EIA API.
    
    Endpoint: Petroleum Data - Refinery Stocks
    Series includes: Jet Fuel Inventory (US aggregate)
    Frequency: Weekly
    """
    if not rc.require_real_mode("EIA jet fuel inventory API"):
        logger.info("DEV mode: skipping EIA jet fuel inventory API call")
        return pd.DataFrame()
    
    if not EIA_API_KEY:
        logger.warning("EIA_API_KEY not set. Skipping jet fuel inventory fetch.")
        return pd.DataFrame()
    
    try:
        # EIA API endpoint for refinery stocks
        url = "https://api.eia.gov/v2/petroleum/stk/stk_jf/data/"
        
        params = {
            "api_key": EIA_API_KEY,
            "frequency": "weekly",
            "data[0]": "value",
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": 500
        }
        
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        if 'response' not in data or 'data' not in data['response']:
            logger.warning("Unexpected EIA API response structure for inventory")
            return pd.DataFrame()
        
        df = pd.DataFrame(data['response']['data'])
        
        if df.empty:
            logger.warning("No jet fuel inventory data returned from EIA API")
            return pd.DataFrame()
        
        # Normalize timestamp column
        df['timestamp'] = pd.to_datetime(df['period'])
        df = df.rename(columns={'value': 'inventory_million_bbl'})
        
        # Convert to numeric, drop nulls
        df['inventory_million_bbl'] = pd.to_numeric(df['inventory_million_bbl'], errors='coerce')
        df = df.dropna(subset=['inventory_million_bbl'])
        
        # Select relevant columns
        df = df[['timestamp', 'inventory_million_bbl']]
        df = df.sort_values('timestamp')
        
        logger.info(f"Fetched {len(df)} jet fuel inventory records")
        logger.info(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
        
        return df
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching jet fuel inventory: {e}")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Unexpected error in jet fuel inventory fetch: {e}")
        return pd.DataFrame()


def calculate_jet_fuel_indicators(prod_df: pd.DataFrame, inv_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate supply-side indicators from production and inventory data.
    
    Indicators:
    - Weeks of supply (inventory / weekly production)
    - YoY production change %
    - Production 4-week moving average
    - Inventory trend
    """
    if prod_df.empty and inv_df.empty:
        return pd.DataFrame()
    
    # Merge on timestamp if we have both
    if not prod_df.empty and not inv_df.empty:
        df = pd.merge(prod_df, inv_df, on='timestamp', how='outer')
    elif not prod_df.empty:
        df = prod_df.copy()
    else:
        df = inv_df.copy()
    
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    # Calculate weeks of supply if both available
    if 'production_thousand_bpd' in df.columns and 'inventory_million_bbl' in df.columns:
        # Convert units: inventory (million bbl) / production (thousand bpd)
        # weeks_of_supply = (inventory_million_bbl * 1000) / (production_thousand_bpd * 7)
        df['weeks_of_supply'] = (
            (df['inventory_million_bbl'] * 1000) / 
            (df['production_thousand_bpd'] * 7)
        ).round(2)
    
    # YoY production change
    if 'production_thousand_bpd' in df.columns:
        df['production_yoy_pct_change'] = df['production_thousand_bpd'].pct_change(52) * 100
        
        # 4-week moving average
        df['production_ma4w'] = df['production_thousand_bpd'].rolling(window=4, min_periods=1).mean()
    
    # Inventory trend
    if 'inventory_million_bbl' in df.columns:
        df['inventory_change_pct'] = df['inventory_million_bbl'].pct_change() * 100
    
    return df


def save_jet_fuel_data(df: pd.DataFrame) -> bool:
    """Save processed jet fuel data to database."""
    if df.empty:
        logger.warning("No jet fuel data to save")
        return False
    
    try:
        engine = create_engine(DB_URL)
        df.to_sql('eia_jet_fuel', engine, if_exists='replace', index=False)
        logger.info(f"Saved {len(df)} jet fuel records to database")
        return True
    except Exception as e:
        logger.error(f"Error saving jet fuel data to database: {e}")
        return False


def ingest_eia_jet_fuel():
    """Main ingestion function for EIA jet fuel data."""
    rc.log_mode("EIA Jet Fuel")
    logger.info("Starting EIA jet fuel data ingestion...")
    
    # Fetch production and inventory
    prod_df = fetch_jet_fuel_production()
    inv_df = fetch_jet_fuel_inventory()
    
    if prod_df.empty and inv_df.empty:
        logger.warning("No jet fuel data fetched from EIA API")
        return pd.DataFrame()
    
    # Calculate indicators
    df = calculate_jet_fuel_indicators(prod_df, inv_df)
    
    # Save to database
    if not df.empty:
        save_jet_fuel_data(df)
        logger.info(f"Jet fuel ingestion complete. Shape: {df.shape}")
    
    return df


def main():
    """Entry point for scheduled ingestion (compatible with run_all_ingesters.py)."""
    return ingest_eia_jet_fuel()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    df = ingest_eia_jet_fuel()
    
    if not df.empty:
        print("\nRecent jet fuel supply data:")
        print(df[['timestamp', 'production_thousand_bpd', 'inventory_million_bbl', 'weeks_of_supply']].tail(10))
        print(f"\nSummary statistics:")
        numeric_cols = df.select_dtypes(include=['number']).columns
        print(df[numeric_cols].describe())
    else:
        print("No data to display")
