"""
CME futures data ingestion via Yahoo Finance.

Fetches historical futures data for:
- Crude oil (CL=F for WTI)
- Natural gas (NG=F)
- Henry Hub natural gas spreads
- Heating oil (HO=F)
- RBOB Gasoline (RB=F)

CME futures provide:
- Price discovery (forward-looking)
- Volatility indicators
- Seasonal patterns
- Term structure analysis
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import logging
from typing import List, Dict, Optional
import json

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "processed"

# CME futures symbols on Yahoo Finance
CME_FUTURES = {
    "crude_oil_wti": {
        "symbol": "CL=F",
        "name": "WTI Crude Oil",
        "contract_unit": "barrels",
        "multiplier": 1000,
        "description": "NYMEX West Texas Intermediate Crude Oil Futures"
    },
    "natural_gas": {
        "symbol": "NG=F",
        "name": "Henry Hub Natural Gas",
        "contract_unit": "MMBtu",
        "multiplier": 10000,
        "description": "NYMEX Henry Hub Natural Gas Futures"
    },
    "heating_oil": {
        "symbol": "HO=F",
        "name": "Heating Oil",
        "contract_unit": "gallons",
        "multiplier": 42000,
        "description": "NYMEX Heating Oil Futures"
    },
    "rbob_gasoline": {
        "symbol": "RB=F",
        "name": "RBOB Gasoline",
        "contract_unit": "gallons",
        "multiplier": 42000,
        "description": "NYMEX RBOB Gasoline Futures"
    },
}


class CMEFuturesClient:
    """Client for fetching CME futures data via Yahoo Finance."""
    
    def __init__(self):
        """Initialize CME futures client."""
        pass
    
    def fetch_futures(self, symbol: str, start_date: Optional[str] = None,
                      end_date: Optional[str] = None, interval: str = "1d") -> pd.DataFrame:
        """
        Fetch historical futures prices from Yahoo Finance.
        
        Args:
            symbol: Yahoo Finance symbol (e.g., 'CL=F' for WTI crude)
            start_date: Start date (YYYY-MM-DD format)
            end_date: End date (YYYY-MM-DD format)
            interval: '1d' for daily, '1wk' for weekly, '1mo' for monthly
        
        Returns:
            DataFrame with Date, Open, High, Low, Close, Volume
        """
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
        
        try:
            logger.info(f"Fetching {symbol} futures data from {start_date} to {end_date}...")
            
            # Use yfinance to download futures data
            data = yf.download(
                symbol,
                start=start_date,
                end=end_date,
                interval=interval,
                progress=False
            )
            
            if data.empty:
                logger.warning(f"No data returned for {symbol}")
                return pd.DataFrame()
            
            # Reset index to make Date a column
            data = data.reset_index()
            data.rename(columns={'Date': 'Date'}, inplace=True)
            
            logger.info(f"Fetched {len(data)} records for {symbol}")
            return data
        
        except Exception as e:
            logger.error(f"Error fetching {symbol}: {e}")
            return pd.DataFrame()
    
    def fetch_all_futures(self, start_date: Optional[str] = None,
                          end_date: Optional[str] = None) -> pd.DataFrame:
        """
        Fetch data for all tracked CME futures.
        
        Returns:
            Combined DataFrame with all futures prices
        """
        all_data = []
        
        for future_key, config in CME_FUTURES.items():
            symbol = config["symbol"]
            
            df = self.fetch_futures(symbol, start_date, end_date)
            
            if not df.empty:
                df["contract"] = future_key
                df["symbol"] = symbol
                df["name"] = config["name"]
                all_data.append(df)
        
        if all_data:
            combined = pd.concat(all_data, ignore_index=True)
            return combined
        else:
            logger.warning("No futures data retrieved")
            return pd.DataFrame()


def calculate_futures_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate technical indicators and derived metrics.
    
    Adds:
    - Price momentum (% change over periods)
    - Volatility
    - Moving averages
    - Spreads between contracts
    """
    df = df.copy()
    
    # Group by contract for calculations
    for contract in df["contract"].unique():
        mask = df["contract"] == contract
        
        # YoY change
        df.loc[mask, "Close_YoY_Pct"] = (
            df.loc[mask, "Close"].pct_change(252) * 100
        )
        
        # Month-to-date change
        df.loc[mask, "Close_MTD_Pct"] = (
            df.loc[mask, "Close"].pct_change() * 100
        )
        
        # 20-day moving average
        df.loc[mask, "MA_20"] = (
            df.loc[mask, "Close"].rolling(window=20, min_periods=1).mean()
        )
        
        # 200-day moving average
        df.loc[mask, "MA_200"] = (
            df.loc[mask, "Close"].rolling(window=200, min_periods=1).mean()
        )
        
        # Volatility (20-day rolling std)
        df.loc[mask, "Volatility_20d"] = (
            df.loc[mask, "Close"].rolling(window=20, min_periods=1).std()
        )
        
        # High-Low range (daily volatility proxy)
        df.loc[mask, "Range_Pct"] = (
            (df.loc[mask, "High"] - df.loc[mask, "Low"]) / 
            df.loc[mask, "Close"] * 100
        )
    
    return df


def save_futures_data(df: pd.DataFrame, output_path: Optional[Path] = None) -> Path:
    """Save CME futures data to CSV."""
    if output_path is None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / "cme_futures.csv"
    
    if not df.empty:
        df.to_csv(output_path, index=False)
        logger.info(f"Saved futures data to {output_path}")
        
        # Save metadata
        metadata = {
            "created": datetime.now().isoformat(),
            "contracts": list(CME_FUTURES.keys()),
            "symbols": {k: v["symbol"] for k, v in CME_FUTURES.items()},
            "data_source": "Yahoo Finance",
            "total_records": len(df),
            "date_range": f"{df['Date'].min()} to {df['Date'].max()}",
            "indicators": [
                "Close_YoY_Pct: Year-over-year price change %",
                "Close_MTD_Pct: Daily price change %",
                "MA_20: 20-day moving average",
                "MA_200: 200-day moving average",
                "Volatility_20d: 20-day rolling standard deviation",
                "Range_Pct: Daily high-low range as % of close"
            ]
        }
        
        metadata_path = output_path.with_suffix(".json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2, default=str)
        
        logger.info(f"Saved metadata to {metadata_path}")
    
    return output_path


def ingest_cme_futures():
    """Main ingestion function for CME futures."""
    logger.info("Starting CME futures data ingestion...")
    
    client = CMEFuturesClient()
    
    # Fetch all futures data
    logger.info(f"Fetching CME futures for: {list(CME_FUTURES.keys())}")
    
    df = client.fetch_all_futures()
    
    if not df.empty:
        # Calculate indicators
        df = calculate_futures_indicators(df)
        
        # Save to disk
        output_path = save_futures_data(df)
        
        logger.info(f"Futures ingestion complete. Total records: {len(df)}")
        
        # Summary by contract
        logger.info("Data summary by contract:")
        for contract in df["contract"].unique():
            contract_data = df[df["contract"] == contract]
            latest = contract_data.iloc[-1]
            logger.info(f"  {contract}: {latest['Close']:.2f} "
                       f"(updated {latest['Date']})")
        
        return df
    else:
        logger.warning("No futures data retrieved")
        return pd.DataFrame()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    df = ingest_cme_futures()
    
    if not df.empty:
        print("\nRecent futures prices:")
        for contract in df["contract"].unique():
            contract_df = df[df["contract"] == contract].tail(5)
            print(f"\n{contract}:")
            print(contract_df[["Date", "Close", "MA_20", "Volatility_20d"]].to_string())
