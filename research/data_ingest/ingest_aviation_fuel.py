"""
Aviation fuel data ingestion.

Processes airline fuel consumption and cost data from ODS file.
Includes:
- Monthly domestic/international fuel consumption (gallons)
- Total fuel costs
- Cost per gallon historical trends

This data feeds into aviation demand signals and can be correlated
with jet fuel inventory and airline stock performance.
"""

import sys
import pandas as pd
from datetime import datetime
from pathlib import Path
import logging
from typing import Optional
import json
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).parent.parent))
from common import runtime_config as rc

logger = logging.getLogger(__name__)

AIRLINE_FUEL_FILE = Path(__file__).parent.parent.parent / "data" / "airline_fuel.ods"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "processed"


def load_airline_fuel_data(file_path: Optional[Path] = None) -> pd.DataFrame:
    """
    Load and parse airline fuel consumption data from ODS file.
    
    The file contains:
    - Domestic fuel consumption (gallons)
    - International fuel consumption (gallons)
    - Total fuel consumption
    - Total cost (million dollars)
    - Cost per gallon
    """
    if file_path is None:
        file_path = AIRLINE_FUEL_FILE
    
    if not file_path.exists():
        raise FileNotFoundError(f"Airline fuel file not found: {file_path}")
    
    try:
        df = pd.read_excel(file_path, engine='odf')
        logger.info(f"Loaded ODS file: {file_path}")
        
        # The first row appears to be headers, skip it
        # Real header is in row 0, data starts from row 1
        actual_headers = df.iloc[0].values.tolist()
        
        # Clean up: extract the meaningful data
        df = df.iloc[1:].reset_index(drop=True)
        
        # Identify key columns
        # Looking at the structure:
        # Col 0: Year, Col 1: Month
        # Col 2: Domestic, Col 3: (unlabeled, likely units/notes)
        # Col 4: (unlabeled)
        # Col 5: International
        # Col 6-7: (unlabeled)
        # Col 8: Total
        # Col 9: Cost(million dollars)
        # Col 10: Cost per Gallon
        
        logger.debug(f"Original columns: {df.columns.tolist()}")
        
        # Rename columns to meaningful names
        df = df[['Year', 'Month', 'Domestic', 'International', 'Total', 
                 'Unnamed: 9', 'Unnamed: 10']]
        df.columns = ['Year', 'Month', 'Domestic_Gallons', 'International_Gallons', 
                      'Total_Gallons', 'Total_Cost_Million', 'Cost_Per_Gallon']
        
        # Convert to proper types
        df['Year'] = pd.to_numeric(df['Year'], errors='coerce')
        df['Month'] = df['Month'].astype(str).str.strip()
        df['Domestic_Gallons'] = pd.to_numeric(df['Domestic_Gallons'], errors='coerce')
        df['International_Gallons'] = pd.to_numeric(df['International_Gallons'], errors='coerce')
        df['Total_Gallons'] = pd.to_numeric(df['Total_Gallons'], errors='coerce')
        df['Total_Cost_Million'] = pd.to_numeric(df['Total_Cost_Million'], errors='coerce')
        df['Cost_Per_Gallon'] = pd.to_numeric(df['Cost_Per_Gallon'], errors='coerce')
        
        # Drop rows with missing Year
        df = df.dropna(subset=['Year'])
        
        # Create proper date column
        month_map = {
            'January': 1, 'February': 2, 'March': 3, 'April': 4,
            'May': 5, 'June': 6, 'July': 7, 'August': 8,
            'September': 9, 'October': 10, 'November': 11, 'December': 12
        }
        
        df['Month_Num'] = df['Month'].map(month_map)
        
        # Create datetime
        df['Date'] = pd.to_datetime(
            df['Year'].astype(int).astype(str) + '-' + 
            df['Month_Num'].astype(int).astype(str) + '-01'
        )
        
        # Reorder and clean
        df = df[['Date', 'Year', 'Month', 'Domestic_Gallons', 'International_Gallons',
                 'Total_Gallons', 'Total_Cost_Million', 'Cost_Per_Gallon']]
        
        # Sort by date
        df = df.sort_values('Date').reset_index(drop=True)
        
        logger.info(f"Processed airline fuel data: {len(df)} records")
        logger.info(f"Date range: {df['Date'].min()} to {df['Date'].max()}")
        
        return df
        
    except Exception as e:
        logger.error(f"Error loading airline fuel data: {e}")
        raise


def calculate_aviation_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate aviation demand indicators from fuel data.
    
    Indicators:
    - YoY growth in fuel consumption
    - Monthly averages by season
    - Implied domestic/international split
    - Cost efficiency trends
    """
    df = df.copy()
    
    # Year-over-year growth
    df['Total_Gallons_YoY_Pct'] = df.groupby('Month')['Total_Gallons'].pct_change(12) * 100
    
    # Domestic as percentage of total
    df['Domestic_Pct'] = (df['Domestic_Gallons'] / df['Total_Gallons'] * 100).round(2)
    
    # Cost per thousand gallons (efficiency metric)
    df['Cost_Per_1000Gal'] = (df['Total_Cost_Million'] * 1_000_000 / 
                              (df['Total_Gallons'] * 1000)).round(2)
    
    # 3-month moving average
    df['Total_Gallons_MA3'] = df['Total_Gallons'].rolling(window=3, min_periods=1).mean()
    
    return df


def save_aviation_data(df: pd.DataFrame, output_path: Optional[Path] = None) -> Path:
    """Save processed aviation fuel data to database."""
    if df.empty:
        logger.warning("No aviation fuel data to save")
        return Path()
    
    # Drop Year/Month columns as they're derived from Date
    df_to_save = df.drop(columns=['Year', 'Month'], errors='ignore')
    
    try:
        engine = create_engine(rc.get_db_url())
        # Use replace to handle schema evolution
        df_to_save.to_sql('aviation_fuel', engine, if_exists='replace', index=False)
        logger.info(f"Saved {len(df_to_save)} aviation fuel records to database (schema updated)")
    except Exception as e:
        logger.error(f"Error saving aviation fuel data to database: {e}")
        raise
    
    # Return a dummy path for compatibility
    return Path("aviation_fuel_historical")


def ingest_aviation_fuel():
    """Main ingestion function for aviation fuel data."""
    logger.info("Starting aviation fuel data ingestion...")
    
    # Load data
    df = load_airline_fuel_data()
    
    # Calculate indicators
    df = calculate_aviation_indicators(df)
    
    # Save to disk
    output_path = save_aviation_data(df)
    
    logger.info(f"Aviation fuel ingestion complete. Shape: {df.shape}")
    
    return df


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    df = ingest_aviation_fuel()
    print("\nRecent aviation fuel data:")
    print(df[['Date', 'Total_Gallons', 'Total_Cost_Million', 'Cost_Per_Gallon']].tail(10))
    print(f"\nSummary statistics:")
    print(df[['Total_Gallons', 'Cost_Per_Gallon', 'Domestic_Pct']].describe())
