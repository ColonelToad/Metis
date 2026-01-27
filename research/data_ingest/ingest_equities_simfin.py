"""
SimFin equities data ingestion.

Fetches fundamental and stock price data for energy-related equities:
- Integrated energy companies (XOM, CVX, COP, MPC)
- LNG exporters (CQP, LNG)
- Transportation/shipping (ZIM, DAC)
- Utilities (NEE, D)

Uses SimFin API for reliable fundamental data including:
- Stock prices (daily)
- P/E ratios, dividend yields
- Revenue, earnings trends
- Cash flow metrics
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import logging
from typing import List, Dict, Optional
import json
import os

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "processed"

# SimFin API endpoints
SIMFIN_API_URL = "https://api.simfin.com/api/v2"

# Energy sector tickers to track
ENERGY_TICKERS = {
    "integrated_energy": ["XOM", "CVX", "COP"],  # Exxon, Chevron, ConocoPhillips
    "refiners": ["MPC", "VLO"],  # Marathon, Valero
    "lng_exporters": ["CQP"],  # Cheniere (LNG exporter)
    "shipping": ["ZIM", "DAC"],  # Zim, Danaos (container/shipping)
    "energy_services": ["SLB", "HAL"],  # Schlumberger, Halliburton
    "utilities": ["NEE", "D"],  # NextEra (renewable), Dominion (diversified)
}

# Flatten ticker list
ALL_TICKERS = []
for sector_tickers in ENERGY_TICKERS.values():
    ALL_TICKERS.extend(sector_tickers)


class SimFinClient:
    """Client for SimFin API."""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize SimFin client with API key."""
        self.api_key = api_key or os.getenv("SIMFIN_API_KEY")
        if not self.api_key:
            logger.warning("SimFin API key not found in environment variables. "
                          "Set SIMFIN_API_KEY environment variable.")
    
    def fetch_prices(self, ticker: str, start_date: Optional[str] = None,
                     end_date: Optional[str] = None) -> pd.DataFrame:
        """
        Fetch historical stock prices for a ticker.
        
        Args:
            ticker: Stock ticker symbol
            start_date: Start date (YYYY-MM-DD format)
            end_date: End date (YYYY-MM-DD format)
        
        Returns:
            DataFrame with Date, Close, Volume, etc.
        """
        if not self.api_key:
            logger.warning(f"Cannot fetch {ticker}: API key not configured")
            return pd.DataFrame()
        
        # Default to last 2 years if not specified
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
        
        try:
            # SimFin uses different endpoints for different data types
            # For stock prices, use the prices endpoint
            endpoint = f"{SIMFIN_API_URL}/companies/ticker/{ticker}/prices"
            
            params = {
                "api-key": self.api_key,
                "start": start_date,
                "end": end_date,
            }
            
            response = requests.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if "data" in data:
                df = pd.DataFrame(data["data"])
                df["Date"] = pd.to_datetime(df["Date"])
                df = df.sort_values("Date").reset_index(drop=True)
                logger.info(f"Fetched {len(df)} price records for {ticker}")
                return df
            else:
                logger.warning(f"No price data returned for {ticker}")
                return pd.DataFrame()
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching prices for {ticker}: {e}")
            return pd.DataFrame()
    
    def fetch_fundamentals(self, ticker: str) -> Dict:
        """
        Fetch fundamental data for a ticker.
        
        Returns metrics like:
        - P/E ratio
        - Dividend yield
        - ROE, ROA
        - Debt ratios
        """
        if not self.api_key:
            return {}
        
        try:
            # Fundamental data endpoint
            endpoint = f"{SIMFIN_API_URL}/companies/ticker/{ticker}/fundamentals"
            
            params = {
                "api-key": self.api_key,
                "statements": "all",
            }
            
            response = requests.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Fetched fundamental data for {ticker}")
            return data
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching fundamentals for {ticker}: {e}")
            return {}
    
    def fetch_all_sectors(self) -> pd.DataFrame:
        """
        Fetch price data for all tracked energy sector stocks.
        
        Returns:
            DataFrame with tickers and latest price data
        """
        all_data = []
        
        for ticker in ALL_TICKERS:
            logger.info(f"Fetching {ticker}...")
            prices_df = self.fetch_prices(ticker)
            
            if not prices_df.empty:
                latest = prices_df.iloc[-1]
                all_data.append({
                    "date": latest.get("Date"),
                    "ticker": ticker,
                    "close": latest.get("Close"),
                    "volume": latest.get("Volume"),
                })
        
        return pd.DataFrame(all_data) if all_data else pd.DataFrame()


def save_equity_data(prices_df: pd.DataFrame, output_path: Optional[Path] = None) -> Path:
    """Save equity price data to CSV."""
    if output_path is None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / "energy_equities.csv"
    
    if not prices_df.empty:
        prices_df.to_csv(output_path, index=False)
        logger.info(f"Saved equity data to {output_path}")
        
        # Save metadata
        metadata = {
            "created": datetime.now().isoformat(),
            "tickers": ALL_TICKERS,
            "sectors": ENERGY_TICKERS,
            "data_source": "SimFin API",
        }
        
        metadata_path = output_path.with_suffix(".json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2, default=str)
        
        logger.info(f"Saved metadata to {metadata_path}")
    
    return output_path


def ingest_equities():
    """Main ingestion function for SimFin equity data."""
    logger.info("Starting SimFin equity data ingestion...")
    
    client = SimFinClient()
    
    # Fetch data for all tracked tickers
    logger.info(f"Fetching data for {len(ALL_TICKERS)} tickers: {ALL_TICKERS}")
    
    all_prices = []
    for ticker in ALL_TICKERS:
        prices = client.fetch_prices(ticker)
        if not prices.empty:
            prices["ticker"] = ticker
            all_prices.append(prices)
    
    if all_prices:
        combined_df = pd.concat(all_prices, ignore_index=True)
        
        # Save to disk
        output_path = save_equity_data(combined_df)
        
        logger.info(f"Equity ingestion complete. Total records: {len(combined_df)}")
        
        return combined_df
    else:
        logger.warning("No equity data fetched. Check API key configuration.")
        return pd.DataFrame()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    df = ingest_equities()
    if not df.empty:
        print("\nRecent equity data:")
        print(df.groupby("ticker")[["Date", "Close"]].tail(1))
    else:
        print("No data retrieved. Configure SIMFIN_API_KEY environment variable.")
