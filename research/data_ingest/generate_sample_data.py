import pandas as pd
import numpy as np
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

# Ensure output directory exists
output_dir = Path('data/tick_data')
output_dir.mkdir(parents=True, exist_ok=True)

# Generate realistic tick data
start_time = datetime(2024, 1, 1, 9, 0)
num_ticks = 10000
base_price = 2.50
timestamps = [start_time + timedelta(seconds=i) for i in range(num_ticks)]
prices = base_price + np.random.randn(num_ticks).cumsum() * 0.001
df = pd.DataFrame({
    'timestamp': timestamps,
    'symbol': 'NGZ24',
    'bid': prices - 0.002,
    'ask': prices + 0.002,
    'bid_quantity': np.random.randint(50, 200, num_ticks),
    'ask_quantity': np.random.randint(50, 200, num_ticks),
    'last': prices,
    'volume': np.random.randint(1, 50, num_ticks),
})

df.to_csv(output_dir / 'NGZ24_sample.csv', index=False)
print(f"Generated {len(df)} sample ticks")
