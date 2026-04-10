"""
Data ingestion client for CME Natural Gas futures tick data.
Supports Databento and CME DataMine formats.
"""
import pandas as pd
import pyarrow.parquet as pq
from pathlib import Path
from typing import Optional, List
from datetime import datetime
from loguru import logger
import struct


class TickDataIngester:
    """
    Ingest and parse tick data from various sources.
    Standardizes to common format for downstream processing.
    """
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def parse_databento_csv(self, filepath: Path) -> pd.DataFrame:
        """
        Parse Databento CSV format tick data.
        
        Expected columns: timestamp, symbol, bid, ask, bid_size, ask_size, last, volume
        """
        try:
            df = pd.read_csv(filepath)
            
            # Standardize column names
            df = df.rename(columns={
                'ts_recv': 'timestamp',
                'bid_px': 'bid',
                'ask_px': 'ask',
                'bid_sz': 'bid_quantity',
                'ask_sz': 'ask_quantity',
            })
            
            # Convert timestamp to datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # Calculate derived fields
            df['mid_price'] = (df['bid'] + df['ask']) / 2
            df['spread'] = df['ask'] - df['bid']
            df['spread_bps'] = (df['spread'] / df['mid_price']) * 10000
            
            logger.info(f"Parsed {len(df)} ticks from {filepath.name}")
            return df
            
        except Exception as e:
            logger.error(f"Failed to parse Databento CSV: {e}")
            return pd.DataFrame()
    
    def parse_cme_pcap(self, filepath: Path) -> pd.DataFrame:
        """
        Parse CME PCAP format (MDP 3.0 protocol).
        This is a simplified parser - production would use proper MDP decoder.
        """
        # TODO: Implement full MDP 3.0 parser
        # For now, assume preprocessed CSV from PCAP
        logger.warning("PCAP parsing not fully implemented - use CSV export")
        return pd.DataFrame()
    
    def load_tick_data(
        self, 
        symbol: str,
        start_date: str,
        end_date: str,
        source: str = "databento"
    ) -> pd.DataFrame:
        """
        Load tick data for given symbol and date range.
        
        Args:
            symbol: Instrument symbol (e.g., "NGZ24" for Dec 2024 NG)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            source: Data source ("databento" or "cme")
        
        Returns:
            DataFrame with tick data
        """
        # Look for cached parquet file first
        cache_file = self.data_dir / f"{symbol}_{start_date}_{end_date}.parquet"
        
        if cache_file.exists():
            logger.info(f"Loading cached data from {cache_file}")
            return pd.read_parquet(cache_file)
        
        # Otherwise load from CSV and cache
        csv_pattern = f"{symbol}_*.csv"
        csv_files = sorted(self.data_dir.glob(csv_pattern))
        
        if not csv_files:
            logger.error(f"No CSV files found matching {csv_pattern}")
            return pd.DataFrame()
        
        dfs = []
        for csv_file in csv_files:
            if source == "databento":
                df = self.parse_databento_csv(csv_file)
            else:
                df = self.parse_cme_pcap(csv_file)
            
            if not df.empty:
                dfs.append(df)
        
        if not dfs:
            return pd.DataFrame()
        
        # Combine and filter by date
        combined = pd.concat(dfs, ignore_index=True)
        combined = combined[
            (combined['timestamp'] >= start_date) &
            (combined['timestamp'] <= end_date)
        ].sort_values('timestamp').reset_index(drop=True)
        
        # Cache as parquet
        combined.to_parquet(cache_file, compression='zstd')
        logger.info(f"Cached {len(combined)} ticks to {cache_file}")
        
        return combined
    
    def resample_to_bars(
        self,
        tick_df: pd.DataFrame,
        freq: str = "1min"
    ) -> pd.DataFrame:
        """
        Resample tick data to OHLCV bars.
        
        Args:
            tick_df: DataFrame with tick data
            freq: Pandas frequency string (e.g., "1min", "5min", "1h")
        
        Returns:
            DataFrame with OHLCV bars
        """
        tick_df = tick_df.set_index('timestamp')
        
        bars = pd.DataFrame({
            'open': tick_df['mid_price'].resample(freq).first(),
            'high': tick_df['mid_price'].resample(freq).max(),
            'low': tick_df['mid_price'].resample(freq).min(),
            'close': tick_df['mid_price'].resample(freq).last(),
            'volume': tick_df['volume'].resample(freq).sum(),
            'avg_spread_bps': tick_df['spread_bps'].resample(freq).mean(),
        }).dropna()
        
        return bars.reset_index()


if __name__ == "__main__":
    # Example usage
    from research.config import DATA_DIR
    
    ingester = TickDataIngester(DATA_DIR / "tick_data")
    
    # Test with sample data (assumes you have CSV files)
    df = ingester.load_tick_data(
        symbol="NGZ24",
        start_date="2024-01-01",
        end_date="2024-01-07",
        source="databento"
    )
    
    if not df.empty:
        print(f"Loaded {len(df)} ticks")
        print(df.head())
        
        # Resample to 1-minute bars
        bars = ingester.resample_to_bars(df, freq="1min")
        print(f"\nResampled to {len(bars)} 1-minute bars")
        print(bars.head())
