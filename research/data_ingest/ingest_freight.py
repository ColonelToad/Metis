"""
Freight data ingestion and consolidation.

Consolidates multiple freight-related data sources into a unified dataset:
- Container rates (monthly)
- Containerized imports/exports (monthly)
- Loaded import/export containers (monthly)
- Diesel prices (weekly)
- Durable goods purchases (monthly)
- Inventory to sales ratio (monthly)
- Nominal and real imports (monthly)
- West Coast shipping rates (monthly)

FUTURE EXTENSION: Natural Gas Tanker Tracking
----------------------------------------------
The AIS vessel tracking (ingest_ais_maritime.py) currently tracks LNG tanker movements.
To extend for NG-specific flow analysis:

1. Map specific LNG terminals to vessel arrival patterns:
   - Sabine Pass, Freeport, Corpus Christi (TX exports)
   - Cove Point (MD imports)
   - Track: arrival date, cargo volume (mmBTU), origin, discharge port

2. Calculate derived metrics:
   - Export utilization: (vessels loading) / (terminal capacity) per week
   - Import volume: total mmBTU arriving at US ports per week
   - Spot prices vs. utilization correlation
   - Backwardation signal: if import volume ↑ → near-term supply tightness

3. Data sources:
   - AIS data: FREE (MarineTraffic, AISHub)
   - Terminal schedules: Need to scrape or API (Bloomberg, Refinitiv)
   - Port authorities: Houston Port Authority, LA Port Authority (some publish vessel schedules)

4. Challenges:
   - Vessel-to-cargo matching (not always in AIS metadata)
   - Multi-leg journeys (ship unloads at intermediate port)
   - LNG vs LPG vs other cargo types in same vessel
   - Real-time vs. scheduled data quality

Current approach: Use AIS for tanker locations + aggregate import/export values from macroeconomic data.
Next step: Connect specific vessel movements to recorded LNG terminal activity.
"""

import os
import sys
import pandas as pd
from datetime import datetime
from pathlib import Path
import logging
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).parent.parent))
from common import runtime_config as rc

logger = logging.getLogger(__name__)

FREIGHT_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "freight"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "processed"

# Data source configurations
FREIGHT_SOURCES = {
    "Container Rates": {
        "file": "Container Rates_data.csv",
        "frequency": "monthly",
        "metric_col": "Rate",
        "origin_col": "Origin",
        "description": "40ft container rates from Shanghai to LA",
    },
    "Containerized Exports": {
        "file": "Containerized Exports_data.csv",
        "frequency": "monthly",
        "metric_col": "Value",
        "description": "US containerized exports (TEU)",
    },
    "Containerized Imports": {
        "file": "Containerized Imports_data.csv",
        "frequency": "monthly",
        "metric_col": "Value",
        "description": "US containerized imports (TEU)",
    },
    "Diesel Price": {
        "file": "Diesel Price_data.csv",
        "frequency": "weekly",
        "metric_col": "Metric Value",
        "description": "US retail diesel prices ($/gallon)",
    },
    "Durable Goods": {
        "file": "Durable Goods Purchases_data.csv",
        "frequency": "monthly",
        "metric_col": "Metric Value",
        "description": "Durable goods purchases (orders indicator)",
    },
    "Inventory to Sales": {
        "file": "Inventory to Sales Ratio_data.csv",
        "frequency": "monthly",
        "metric_col": "Metric Value",
        "description": "Business inventory to sales ratio",
    },
    "Loaded Exports": {
        "file": "Loaded Export_data.csv",
        "frequency": "monthly",
        "metric_col": "Value",
        "description": "Loaded export containers at select US ports",
    },
    "Loaded Imports": {
        "file": "Loaded Import_data.csv",
        "frequency": "monthly",
        "metric_col": "Value",
        "description": "Loaded import containers at select US ports",
    },
    "Nominal Imports": {
        "file": "Nominal Imports_data.csv",
        "frequency": "monthly",
        "metric_col": "Metric Value",
        "description": "US nominal goods imports (billions USD)",
    },
    "West Coast Shipping": {
        "file": "West Coast Shipping Rates_data.csv",
        "frequency": "monthly",
        "metric_col": "Value",
        "description": "West Coast container shipping rates",
    },
}


def load_freight_data():
    """Load and parse all freight data sources."""
    data = {}
    
    for source_name, config in FREIGHT_SOURCES.items():
        file_path = FREIGHT_DATA_DIR / config["file"]
        
        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            continue
        
        try:
            df = pd.read_csv(file_path)
            
            # Standardize date column
            if "Date" in df.columns:
                df["Date"] = pd.to_datetime(df["Date"])
            
            # For monthly data, extract year-month only
            if config["frequency"] == "monthly" and "Date" in df.columns:
                df["Date"] = df["Date"].dt.to_period("M")
            
            data[source_name] = df
            logger.info(f"Loaded {source_name}: {len(df)} records")
            
        except Exception as e:
            logger.error(f"Error loading {source_name}: {e}")
    
    return data


def consolidate_freight_data(data):
    """
    Consolidate multiple freight data sources into unified dataset.
    
    Strategy:
    - Monthly data sources: merge on year-month period
    - Weekly diesel data: assign to nearest month-end
    - Preserve source granularity in metadata
    """
    
    # Separate monthly and weekly data
    monthly_data = {}
    weekly_data = {}
    
    for source_name, df in data.items():
        config = FREIGHT_SOURCES[source_name]
        if config["frequency"] == "monthly":
            monthly_data[source_name] = df
        else:
            weekly_data[source_name] = df
    
    # Start with a base of unique dates from monthly data
    all_dates = set()
    for df in monthly_data.values():
        all_dates.update(df["Date"].unique())
    
    # Create consolidated dataframe
    consolidated = pd.DataFrame({"Date": sorted(all_dates)})
    
    # Merge monthly data sources
    for source_name, df in monthly_data.items():
        config = FREIGHT_SOURCES[source_name]
        metric_col = config["metric_col"]
        
        # Handle data with Origin/Region column
        if config.get("origin_col") in df.columns:
            # For container rates with multiple origins, use West Coast (LA)
            if source_name == "Container Rates":
                df_filtered = df[df["Origin"].str.contains("West Coast|Los Angeles", case=False, na=False)]
            else:
                df_filtered = df.drop(columns=[config["origin_col"]])
            
            merged = consolidated.merge(
                df_filtered[["Date", metric_col]].rename(columns={metric_col: source_name}),
                on="Date",
                how="left"
            )
        else:
            merged = consolidated.merge(
                df[["Date", metric_col]].rename(columns={metric_col: source_name}),
                on="Date",
                how="left"
            )
        
        consolidated = merged
    
    # Handle weekly diesel data - aggregate to monthly average
    if weekly_data:
        diesel_df = weekly_data.get("Diesel Price")
        if diesel_df is not None:
            diesel_df["YearMonth"] = diesel_df["Date"].dt.to_period("M")
            diesel_monthly = diesel_df.groupby("YearMonth")["Metric Value"].mean().reset_index()
            diesel_monthly["Date"] = diesel_monthly["YearMonth"]
            
            consolidated = consolidated.merge(
                diesel_monthly[["Date", "Metric Value"]].rename(columns={"Metric Value": "Diesel Price"}),
                on="Date",
                how="left"
            )
    
    # Sort by date
    consolidated = consolidated.sort_values("Date").reset_index(drop=True)
    
    return consolidated


def save_consolidated_data(consolidated_df, output_path):
    """Save consolidated freight data to database."""
    if consolidated_df.empty:
        logger.warning("No freight data to save")
        return
    
    # Convert Period dates to strings for SQLite compatibility
    if pd.api.types.is_period_dtype(consolidated_df['Date']):
        consolidated_df['Date'] = consolidated_df['Date'].astype(str)
    
    try:
        engine = create_engine(rc.get_db_url())
        consolidated_df.to_sql('freight_data', engine, if_exists='append', index=False)
        logger.info(f"Saved {len(consolidated_df)} freight records to database")
    except Exception as e:
        logger.error(f"Error saving freight data to database: {e}")
        raise


def ingest_freight():
    """Main ingestion function."""
    logger.info("Starting freight data ingestion...")
    
    # Create output directory if it doesn't exist
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Load and consolidate
    data = load_freight_data()
    consolidated = consolidate_freight_data(data)
    
    # Save results
    output_file = OUTPUT_DIR / "freight_consolidated.csv"
    save_consolidated_data(consolidated, output_file)
    
    logger.info(f"Ingestion complete. Consolidated data shape: {consolidated.shape}")
    return consolidated


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    consolidated = ingest_freight()
    print(consolidated.head())
    print(f"\nShape: {consolidated.shape}")
    print(f"\nColumns: {consolidated.columns.tolist()}")
