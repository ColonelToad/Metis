import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Synthetic climate feature generator for 3 months
start_date = datetime.now() - timedelta(days=90)
end_date = datetime.now()
dates = pd.date_range(start=start_date, end=end_date, freq='H')

np.random.seed(42)
temperature = 20 + 10 * np.sin(np.linspace(0, 10, len(dates))) + np.random.randn(len(dates))
hdd = np.maximum(0, 18 - temperature)
cdd = np.maximum(0, temperature - 18)
windspeed = 5 + 2 * np.random.randn(len(dates))

features = pd.DataFrame({
    'timestamp': dates,
    'temperature': temperature,
    'hdd': hdd,
    'cdd': cdd,
    'windspeed': windspeed,
})

features.to_parquet("../data/processed/weather_features_3months.parquet")
print(f"Saved {len(features)} hourly synthetic weather observations")
