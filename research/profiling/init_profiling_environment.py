"""
Database initialization and schema setup for profiling.
Creates essential tables that are needed but may not exist.
"""

import sqlite3
from pathlib import Path
import os

DB_PATH = "data/metis.db"


def ensure_ng_futures_daily_table():
    """Ensure ng_futures_daily table exists with proper schema."""
    Path("data").mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create ng_futures_daily table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ng_futures_daily (
            date TEXT PRIMARY KEY,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create grid_lmp table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS grid_lmp (
            timestamp DATETIME,
            lmp REAL,
            node_id TEXT,
            iso TEXT,
            PRIMARY KEY (timestamp, node_id)
        )
    """)
    
    # Create fred_macro table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fred_macro (
            timestamp DATETIME PRIMARY KEY,
            cpi_energy REAL,
            retail_gas_price REAL,
            wti_crude_price REAL,
            industrial_production REAL,
            housing_starts REAL,
            personal_consumption REAL
        )
    """)
    
    # Create eia_storage table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS eia_storage (
            timestamp DATETIME PRIMARY KEY,
            storage_bcf REAL
        )
    """)
    
    # Create eia_production table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS eia_production (
            timestamp DATETIME PRIMARY KEY,
            production_mmcf REAL
        )
    """)
    
    conn.commit()
    conn.close()
    print(f"✓ Database schema initialized at {DB_PATH}")


def ensure_model_files():
    """Create placeholder model files for profiling."""
    models_dir = Path("models")
    models_dir.mkdir(parents=True, exist_ok=True)
    
    # Create placeholder scalers file
    scalers_file = models_dir / "scalers_v1.0.pkl"
    if not scalers_file.exists():
        import pickle
        # Create minimal scalers dict (just enough for loading)
        scalers = {
            'features_scaler': None,
            'target_scaler': None,
            'feature_names': []
        }
        with open(scalers_file, 'wb') as f:
            pickle.dump(scalers, f)
        print(f"✓ Created placeholder {scalers_file}")
    else:
        print(f"✓ Model file already exists: {scalers_file}")


def create_sample_ng_futures_data():
    """Create minimal sample data for NG futures if table is empty."""
    from datetime import datetime, timedelta
    import sqlite3
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if table has data
    cursor.execute("SELECT COUNT(*) FROM ng_futures_daily")
    count = cursor.fetchone()[0]
    
    if count == 0:
        # Insert sample data (last 100 days of synthetic prices)
        end_date = datetime.now()
        for i in range(100):
            date = (end_date - timedelta(days=100-i)).date()
            # Synthetic price around 3.0 with some variance
            base_price = 3.0 + (i * 0.01)  # Slight uptrend
            open_price = base_price
            close_price = base_price + 0.05
            high_price = base_price + 0.1
            low_price = base_price - 0.05
            volume = 100000
            
            cursor.execute("""
                INSERT OR REPLACE INTO ng_futures_daily 
                (date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (str(date), open_price, high_price, low_price, close_price, volume))
        
        conn.commit()
        print(f"✓ Inserted 100 sample NG futures records")
    else:
        print(f"✓ NG futures table already has {count} records")
    
    conn.close()


if __name__ == "__main__":
    ensure_ng_futures_daily_table()
    ensure_model_files()
    create_sample_ng_futures_data()
    print("\n✅ Database and model files initialized for profiling")
