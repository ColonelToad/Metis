"""
Climate feature engineering module.
Processes weather data and calculates anomalies.
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import requests
from loguru import logger


class ClimateFeatureEngine:
    """
    Extract climate-related features for natural gas price prediction.
    
    Features:
    - Temperature forecast errors (forecast - actual)
    - Heating Degree Days (HDD) and Cooling Degree Days (CDD)
    - Wind speed for renewable generation proxy
    - Precipitation for hydropower
    """
    
    def __init__(self, regions: List[str]):
        self.regions = regions
        self.base_temp = 65.0  # Fahrenheit for HDD/CDD calculation
        
    def calculate_hdd_cdd(self, temp_f: float) -> Dict[str, float]:
        """Calculate Heating and Cooling Degree Days."""
        if temp_f < self.base_temp:
            hdd = self.base_temp - temp_f
            cdd = 0.0
        else:
            hdd = 0.0
            cdd = temp_f - self.base_temp
        
        return {"hdd": hdd, "cdd": cdd}
    
    def calculate_forecast_error(
        self, 
        forecast_temp: float, 
        actual_temp: float
    ) -> Dict[str, float]:
        """
        Calculate temperature forecast error metrics.
        Positive error = forecast was too warm.
        """
        error = forecast_temp - actual_temp
        abs_error = abs(error)
        squared_error = error ** 2
        
        return {
            "temp_error": error,
            "temp_abs_error": abs_error,
            "temp_squared_error": squared_error,
        }
    
    def fetch_openmeteo_data(
        self, 
        latitude: float, 
        longitude: float,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """
        Fetch weather data from Open-Meteo API.
        
        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        
        Returns:
            DataFrame with hourly weather data
        """
        url = "https://api.open-meteo.com/v1/forecast"
        
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date,
            "end_date": end_date,
            "hourly": [
                "temperature_2m",
                "windspeed_10m",
                "precipitation",
                "cloudcover",
            ],
            "temperature_unit": "fahrenheit",
            "windspeed_unit": "mph",
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            df = pd.DataFrame({
                "timestamp": pd.to_datetime(data["hourly"]["time"]),
                "temperature": data["hourly"]["temperature_2m"],
                "windspeed": data["hourly"]["windspeed_10m"],
                "precipitation": data["hourly"]["precipitation"],
                "cloudcover": data["hourly"]["cloudcover"],
            })
            
            return df
            
        except Exception as e:
            logger.error(f"Failed to fetch Open-Meteo data: {e}")
            return pd.DataFrame()
    
    def engineer_features(self, weather_df: pd.DataFrame) -> pd.DataFrame:
        """
        Engineer climate features from raw weather data.
        
        Args:
            weather_df: DataFrame with temperature, windspeed, etc.
        
        Returns:
            DataFrame with engineered features
        """
        df = weather_df.copy()
        
        # HDD/CDD
        degree_days = df["temperature"].apply(self.calculate_hdd_cdd)
        df["hdd"] = degree_days.apply(lambda x: x["hdd"])
        df["cdd"] = degree_days.apply(lambda x: x["cdd"])
        
        # Rolling statistics
        for window in [6, 12, 24]:  # hours
            df[f"temp_ma_{window}h"] = df["temperature"].rolling(window).mean()
            df[f"temp_std_{window}h"] = df["temperature"].rolling(window).std()
            df[f"wind_ma_{window}h"] = df["windspeed"].rolling(window).mean()
        
        # Temperature extremes
        df["temp_zscore"] = (
            (df["temperature"] - df["temperature"].rolling(168).mean()) / 
            df["temperature"].rolling(168).std()
        )
        
        # Day of week and hour (seasonality)
        df["hour"] = df["timestamp"].dt.hour
        df["day_of_week"] = df["timestamp"].dt.dayofweek
        df["month"] = df["timestamp"].dt.month
        
        # Lag features
        for lag in [1, 2, 3, 6, 12, 24]:
            df[f"temp_lag_{lag}h"] = df["temperature"].shift(lag)
            df[f"hdd_lag_{lag}h"] = df["hdd"].shift(lag)
        
        return df


# Regional coordinates for major natural gas production areas
REGION_COORDS = {
    "PERMIAN": {"lat": 31.8, "lon": -102.4},  # West Texas
    "MARCELLUS": {"lat": 40.5, "lon": -78.5},  # Pennsylvania
    "HAYNESVILLE": {"lat": 32.0, "lon": -94.0},  # Louisiana/Texas border
}


if __name__ == "__main__":
    # Example usage
    logger.info("Testing climate feature engineering...")
    
    engine = ClimateFeatureEngine(regions=["PERMIAN"])
    
    # Fetch sample data
    coords = REGION_COORDS["PERMIAN"]
    df = engine.fetch_openmeteo_data(
        latitude=coords["lat"],
        longitude=coords["lon"],
        start_date="2024-01-01",
        end_date="2024-01-07",
    )
    
    if not df.empty:
        features = engine.engineer_features(df)
        logger.info(f"Generated {len(features.columns)} features")
        print(features.head())
    else:
        logger.error("Failed to fetch weather data")
