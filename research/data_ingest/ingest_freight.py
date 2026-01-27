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
"""

import os
import pandas as pd
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

FREIGHT_DATA_DIR = Path(__file__).parent.parent.parent / "freight"
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
        "metric_col": "Value",
        "description": "Durable goods purchases (orders indicator)",
    },
    "Inventory to Sales": {
        "file": "Inventory to Sales Ratio_data.csv",
        "frequency": "monthly",
        "metric_col": "Value",
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
        "metric_col": "Value",
        "description": "US nominal goods imports (billions USD)",
    },
    "Real Imports": {
        "file": "Real Imports_data.csv",
        "frequency": "monthly",
        "metric_col": "Value",
        "description": "US real goods imports (billions USD, 2017 chain-weighted)",
    },
    "West Coast Shipping": {
        "file": "West Coast Shipping Rates_data.csv",
        "frequency": "monthly",
        "metric_col": "Rate",
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
    """Save consolidated freight data to CSV."""
    consolidated_df.to_csv(output_path, index=False)
    logger.info(f"Saved consolidated freight data to {output_path}")
    
    # Also create metadata file
    metadata = {
        "created": datetime.now().isoformat(),
        "rows": len(consolidated_df),
        "columns": list(consolidated_df.columns),
        "date_range": f"{consolidated_df['Date'].min()} to {consolidated_df['Date'].max()}",
        "sources": list(FREIGHT_SOURCES.keys()),
        "source_descriptions": {k: v["description"] for k, v in FREIGHT_SOURCES.items()},
    }
    
    import json
    metadata_path = output_path.with_suffix(".json")
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2, default=str)
    
    logger.info(f"Saved metadata to {metadata_path}")


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
