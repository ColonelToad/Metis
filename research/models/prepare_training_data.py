import pandas as pd
import os

# Paths
script_dir = os.path.dirname(os.path.abspath(__file__))

# Build paths relative to the script's location
weather_path = os.path.join(script_dir, "..", "data", "processed", "weather_features_3months.parquet")
tick_data_path = os.path.join(script_dir, "..", "data", "tick_data", "NGZ24_sample.csv")
output_path = os.path.join(script_dir, "..", "data", "processed", "training_data.parquet")
print(f"Current working directory: {os.getcwd()}")
print(f"Looking for file at: {os.path.abspath(tick_data_path)}")
# Load synthetic weather features
df_weather = pd.read_parquet(weather_path)

# Load tick data (market data)
df_tick = pd.read_csv(tick_data_path, parse_dates=["timestamp"])

# Merge on nearest hour
df_tick["timestamp_hour"] = df_tick["timestamp"].dt.floor("H")
df_merged = pd.merge_asof(
    df_tick.sort_values("timestamp_hour"),
    df_weather.sort_values("timestamp"),
    left_on="timestamp_hour",
    right_on="timestamp",
    direction="backward"
)

# Drop helper columns
df_merged = df_merged.drop(columns=["timestamp_hour"]) 

# Save merged training data
df_merged.to_parquet(output_path)
print(f"Saved merged training data: {len(df_merged)} rows to {output_path}")
