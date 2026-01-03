import pandas as pd
from sqlalchemy import create_engine
from config import DB_URL
from pathlib import Path

# Path to generated sample data
csv_path = Path('data/tick_data/NGZ24_sample.csv')

# Read tick data
if not csv_path.exists():
    raise FileNotFoundError(f"Sample data not found: {csv_path}")

df = pd.read_csv(csv_path)
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Calculate spread in basis points
mid = (df['bid'] + df['ask']) / 2
spread = df['ask'] - df['bid']
df['spread_bps'] = (spread / mid) * 10000

# Load to database
engine = create_engine(DB_URL)
df.to_sql('market_data', engine, if_exists='append', index=False)

print(f"Loaded {len(df)} ticks to database")

# Verify
result = pd.read_sql("SELECT COUNT(*) FROM market_data", engine)
print(f"Total ticks in DB: {result.iloc[0, 0]}")
