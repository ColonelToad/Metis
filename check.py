import pandas as pd
df = pd.read_parquet('data/cache/storm_events/storm_events_2015_20260323.parquet')
print(df['BEGIN_DATE_TIME'].head(10).tolist())
print(df['BEGIN_DATE_TIME'].isna().sum(), "/", len(df), "already-null before parsing")