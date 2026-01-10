"""
BTS Aviation Fuel Data Ingestion
Fetches aviation fuel consumption data from Bureau of Transportation Statistics
Data requires manual download from web form (no direct API)
This script provides utilities to process downloaded CSV files
"""
import os
from pathlib import Path
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
METIS_MODE = os.getenv("METIS_MODE", "DEV")


def require_real_mode(source: str) -> bool:
    if METIS_MODE != "REAL":
        print(f"[DEV MODE] Skipping {source}")
        return False
    return True

DOWNLOAD_INSTRUCTIONS = """
BTS Aviation Fuel Data Download Instructions:
1. Visit: https://www.transtats.bts.gov/DL_SelectFields.asp?gnoyr_VQ=FGK
2. Select:
   - Year and Month
   - All carriers or specific ones
   - Data fields: Fuel Gallons, Fuel Cost
3. Download ZIP file
4. Extract CSV
5. Place CSV in: data/downloads/bts_fuel_*.csv
6. Run this script to import

Or for automated download, set BTS_AUTOMATED=true and ensure Selenium is installed:
pip install selenium
"""


def parse_fuel_csv(csv_path: str) -> pd.DataFrame:
    """
    Parse downloaded BTS fuel consumption CSV
    
    Args:
        csv_path: Path to downloaded BTS CSV file
    """
    try:
        df = pd.read_csv(csv_path, low_memory=False)
        
        # Clean column names
        df.columns = df.columns.str.strip().str.upper()
        
        # Key columns (adjust based on actual BTS format):
        # CARRIER, YEAR, MONTH, FUEL_GALLONS, FUEL_COST_PER_GALLON
        
        required_cols = ['YEAR', 'MONTH']
        if not all(col in df.columns for col in required_cols):
            print(f"Warning: Expected columns not found. Available: {df.columns.tolist()}")
        
        # Convert date
        if 'YEAR' in df.columns and 'MONTH' in df.columns:
            df['date'] = pd.to_datetime(
                df['YEAR'].astype(str) + '-' + df['MONTH'].astype(str).str.zfill(2) + '-01'
            )
        
        # Handle fuel columns (may have different names)
        fuel_col = next((c for c in df.columns if 'FUEL' in c and 'GALLONS' in c), None)
        cost_col = next((c for c in df.columns if 'FUEL' in c and 'COST' in c), None)
        
        if fuel_col and cost_col:
            df[fuel_col] = pd.to_numeric(df[fuel_col], errors='coerce')
            df[cost_col] = pd.to_numeric(df[cost_col], errors='coerce')
            df['cost_per_gallon'] = df[cost_col] / df[fuel_col]
        
        return df
        
    except Exception as e:
        print(f"Error parsing fuel CSV: {e}")
        return pd.DataFrame()


def parse_ontime_performance(csv_path: str) -> pd.DataFrame:
    """
    Parse on-time performance data from BTS
    
    Args:
        csv_path: Path to downloaded CSV
    """
    try:
        df = pd.read_csv(csv_path, low_memory=False)
        
        df.columns = df.columns.str.strip().str.upper()
        
        # Parse dates
        if 'FL_DATE' in df.columns:
            df['FL_DATE'] = pd.to_datetime(df['FL_DATE'])
        
        print(f"Loaded {len(df)} flight records")
        return df
        
    except Exception as e:
        print(f"Error parsing on-time CSV: {e}")
        return pd.DataFrame()


def normalize_and_save(df: pd.DataFrame, data_type: str = "fuel") -> None:
    """Normalize BTS data and save to SQLite"""
    if df.empty:
        print(f"No BTS {data_type} data to save")
        return
    # Build normalized frame with primary keys
    if data_type == "fuel":
        # Expect columns: date, carrier (if available), fuel_gallons, fuel_cost, cost_per_gallon
        carrier = df.get('CARRIER') if 'CARRIER' in df.columns else df.get('UNIQUE_CARRIER')
        if carrier is None:
            carrier = "ALL"
        df['carrier'] = carrier if isinstance(carrier, str) else carrier.fillna("ALL")
        df['id'] = df['carrier'].astype(str) + '_' + df['date'].astype(str)
        df['fuel_gallons'] = df.filter(regex='FUEL.*GALLONS', axis=1).iloc[:, 0] if any(df.columns.str.contains('FUEL')) else df.get('FUEL_GALLONS')
        df['fuel_cost'] = df.filter(regex='FUEL.*COST', axis=1).iloc[:, 0] if any(df.columns.str.contains('FUEL')) else df.get('FUEL_COST')
        df['cost_per_gallon'] = df.get('cost_per_gallon') if 'cost_per_gallon' in df.columns else df['fuel_cost'] / df['fuel_gallons']
        df['timestamp'] = datetime.now()
        df_normalized = df[['id', 'date', 'carrier', 'fuel_gallons', 'fuel_cost', 'cost_per_gallon', 'timestamp']]
    else:
        # ontime: expect FL_DATE and carrier
        carrier = df.get('OP_CARRIER', "")
        df['carrier'] = carrier if isinstance(carrier, str) else carrier.fillna("")
        df['date'] = pd.to_datetime(df.get('date', df.get('FL_DATE', datetime.now())), errors='coerce')
        df['id'] = df['carrier'].astype(str) + '_' + df['date'].astype(str)
        if 'avg_dep_delay' not in df.columns and 'DEP_DELAY' in df.columns:
            df['avg_dep_delay'] = df['DEP_DELAY']
        if 'avg_arr_delay' not in df.columns and 'ARR_DELAY' in df.columns:
            df['avg_arr_delay'] = df['ARR_DELAY']
        df['timestamp'] = datetime.now()
        df_normalized = df[['id', 'date', 'carrier', 'avg_dep_delay', 'avg_arr_delay', 'timestamp']]

    df_normalized = df_normalized.drop_duplicates(subset=['id'], keep='last')
    for col in ['date', 'timestamp']:
        if col in df_normalized.columns:
            df_normalized[col] = pd.to_datetime(df_normalized[col], errors='coerce').dt.tz_localize(None)

    def _to_py(val):
        if pd.isna(val):
            return None
        if isinstance(val, pd.Timestamp):
            return val.to_pydatetime()
        return val

    table_name = f"aviation_{data_type}"

    try:
        engine = create_engine(DB_URL)
        backend = engine.url.get_backend_name()

        with engine.begin() as conn:
            if backend == "sqlite":
                if data_type == "fuel":
                    cols = ['id', 'date', 'carrier', 'fuel_gallons', 'fuel_cost', 'cost_per_gallon', 'timestamp']
                else:
                    cols = ['id', 'date', 'carrier', 'avg_dep_delay', 'avg_arr_delay', 'timestamp']

                records = []
                for row in df_normalized.itertuples(index=False):
                    rec = {c: getattr(row, c) for c in cols if hasattr(row, c)}
                    # Ensure Python types
                    rec['date'] = _to_py(rec.get('date'))
                    rec['timestamp'] = _to_py(rec.get('timestamp'))
                    if 'fuel_gallons' in rec:
                        rec['fuel_gallons'] = None if pd.isna(rec['fuel_gallons']) else float(rec['fuel_gallons'])
                    if 'fuel_cost' in rec:
                        rec['fuel_cost'] = None if pd.isna(rec['fuel_cost']) else float(rec['fuel_cost'])
                    if 'cost_per_gallon' in rec:
                        rec['cost_per_gallon'] = None if pd.isna(rec['cost_per_gallon']) else float(rec['cost_per_gallon'])
                    if 'avg_dep_delay' in rec:
                        rec['avg_dep_delay'] = None if pd.isna(rec['avg_dep_delay']) else float(rec['avg_dep_delay'])
                    if 'avg_arr_delay' in rec:
                        rec['avg_arr_delay'] = None if pd.isna(rec['avg_arr_delay']) else float(rec['avg_arr_delay'])
                    records.append(rec)

                placeholders = ", ".join([f":{c}" for c in cols])
                update_clause = ", ".join([f"{c}=excluded.{c}" for c in cols if c != 'id'])
                stmt = text(
                    f"""
                    INSERT INTO {table_name} ({', '.join(cols)})
                    VALUES ({placeholders})
                    ON CONFLICT(id) DO UPDATE SET {update_clause}
                    """
                )
                conn.execute(stmt, records)
            else:
                df_normalized.to_sql(
                    table_name,
                    conn,
                    if_exists='append',
                    index=False,
                    method='multi'
                )

        print(f"Saved {len(df_normalized)} BTS {data_type} records to database")

    except Exception as e:
        print(f"Error saving BTS {data_type} data to database: {e}")


def find_and_process_downloads() -> None:
    """Find and process any BTS CSV files in downloads directory"""
    download_dir = Path("data/downloads")
    
    if not download_dir.exists():
        print(f"Download directory not found: {download_dir}")
        print(DOWNLOAD_INSTRUCTIONS)
        return
    
    csv_files = list(download_dir.glob("bts_*.csv"))
    
    if not csv_files:
        print(f"No BTS CSV files found in {download_dir}")
        print(DOWNLOAD_INSTRUCTIONS)
        return
    
    for csv_file in csv_files:
        print(f"\nProcessing: {csv_file}")
        
        if "fuel" in csv_file.name.lower():
            df = parse_fuel_csv(str(csv_file))
            normalize_and_save(df, "fuel")
        elif "ontime" in csv_file.name.lower():
            df = parse_ontime_performance(str(csv_file))
            # Extract delay statistics
            if not df.empty and 'DEP_DELAY' in df.columns:
                df_normalized = pd.DataFrame({
                    'date': df['FL_DATE'],
                    'avg_dep_delay': df['DEP_DELAY'],
                    'avg_arr_delay': df['ARR_DELAY'],
                    'carrier': df.get('OP_CARRIER', ''),
                    'timestamp': datetime.now()
                })
                normalize_and_save(df_normalized, "ontime")


if __name__ == "__main__":
    print(f"[{METIS_MODE}] BTS Aviation Data Processor")

    print("=" * 50)
    print(DOWNLOAD_INSTRUCTIONS)
    print("\nProcessing any available downloaded files...")

    find_and_process_downloads()
