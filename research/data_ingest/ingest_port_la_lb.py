"""
Port of Los Angeles & Long Beach Container Statistics
Parses container volume data from downloaded Excel files
Primary supply chain indicator for US West Coast imports
"""
import os
from pathlib import Path
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import re

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
METIS_MODE = os.getenv("METIS_MODE", "DEV")

# Excel files in data/ports/
DATA_DIR = Path("data/ports")


def require_real_mode(source: str) -> bool:
    if METIS_MODE != "REAL":
        print(f"[DEV MODE] Skipping {source}")
        return False
    return True


def parse_manual_download(
    excel_path: Path, 
    port_name: str = "LA"
) -> pd.DataFrame:
    """
    Parse manually downloaded Excel file from port website
    
    Args:
        excel_path: Path to downloaded Excel file
        port_name: 'LA' or 'LB' (Long Beach)
    
    Expected Excel structure:
    - Sheet: 'Monthly Summary' or first sheet
    - Columns: Date/Year/Month, Loaded Imports, Loaded Exports, Empty Imports, Empty Exports, Total TEUs
    """
    try:
        # Try common sheet names
        sheet_names = ['Monthly Summary', 'Summary', 'Monthly', 'Data']
        df = None
        
        for sheet in sheet_names:
            try:
                df = pd.read_excel(excel_path, sheet_name=sheet)
                break
            except:
                continue
        
        if df is None:
            # Use first sheet
            df = pd.read_excel(excel_path, sheet_name=0)
        
        # Clean column names
        df.columns = df.columns.str.strip().str.replace(' ', '_').str.lower()
        
        # Parse dates
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
        elif 'month' in df.columns and 'year' in df.columns:
            # Combine year and month
            df['date'] = pd.to_datetime(
                df['year'].astype(str) + '-' + df['month'].astype(str).str.zfill(2) + '-01',
                errors='coerce'
            )
        elif 'year' in df.columns:
            # Annual data
            df['date'] = pd.to_datetime(df['year'].astype(str) + '-01-01', errors='coerce')
        
        df['port'] = port_name
        
        # Calculate key metrics - try multiple column name patterns
        teu_cols = [c for c in df.columns if 'teu' in c.lower() and 'total' in c.lower()]
        if teu_cols:
            df['teus'] = pd.to_numeric(df[teu_cols[0]], errors='coerce')
        elif 'total_teus' in df.columns:
            df['teus'] = pd.to_numeric(df['total_teus'], errors='coerce')
        else:
            # Try to sum container types
            import_cols = [c for c in df.columns if 'import' in c.lower() and 'loaded' in c.lower()]
            export_cols = [c for c in df.columns if 'export' in c.lower() and 'loaded' in c.lower()]
            
            if import_cols and export_cols:
                loaded_imports = pd.to_numeric(df[import_cols[0]], errors='coerce').fillna(0)
                loaded_exports = pd.to_numeric(df[export_cols[0]], errors='coerce').fillna(0)
                
                # Try empty containers too
                empty_import_cols = [c for c in df.columns if 'import' in c.lower() and 'empty' in c.lower()]
                empty_export_cols = [c for c in df.columns if 'export' in c.lower() and 'empty' in c.lower()]
                
                empty_imports = pd.to_numeric(df[empty_import_cols[0]], errors='coerce').fillna(0) if empty_import_cols else 0
                empty_exports = pd.to_numeric(df[empty_export_cols[0]], errors='coerce').fillna(0) if empty_export_cols else 0
                
                df['teus'] = loaded_imports + loaded_exports + empty_imports + empty_exports
        
        # Filter to rows with valid dates and TEUs
        df = df.dropna(subset=['date'])
        if 'teus' in df.columns:
            df = df.dropna(subset=['teus'])
        
        return df
        
    except Exception as e:
        print(f"Error parsing port Excel {excel_path}: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def calculate_import_stress_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate supply chain stress indicators
    
    Indicators:
    - Import volume YoY change (>10% = stress)
    - 3-month moving average deviation
    """
    if df.empty or 'teus' not in df.columns:
        return df
    
    # Sort by date
    df = df.sort_values('date').reset_index(drop=True)
    
    # YoY growth
    df['teus_yoy_change'] = df['teus'].pct_change(periods=12) * 100
    
    # 3-month moving average
    df['teus_ma3'] = df['teus'].rolling(window=3).mean()
    df['teus_deviation'] = ((df['teus'] - df['teus_ma3']) / df['teus_ma3'] * 100).fillna(0)
    
    # Stress flag: YoY decline >10% or deviation >15%
    df['supply_chain_stress'] = (
        (df['teus_yoy_change'] < -10) | 
        (df['teus_deviation'] < -15)
    ).astype(int)
    
    return df


def find_and_process_downloads() -> pd.DataFrame:
    """Find and process any port Excel files in downloads directory"""
    if not DATA_DIR.exists():
        print(f"Download directory not found: {DATA_DIR}")
        print("\nTo use this ingester:")
        print("1. Visit Port of LA: https://www.portoflosangeles.org/business/statistics/facts-and-figures")
        print("2. Visit Port of LB: https://polb.com/business/statistics/")
        print("3. Download Excel files (e.g., Monthly_Statistics_2025.xlsx)")
        print(f"4. Save to {DATA_DIR}/")
        print("5. Re-run this script")
        return pd.DataFrame()
    
    excel_files = list(DATA_DIR.glob("*.xlsx")) + list(DATA_DIR.glob("*.xls"))
    
    if not excel_files:
        print(f"No Excel files found in {DATA_DIR}")
        print("\nPlace port statistics Excel files in this directory:")
        print(f"  {DATA_DIR.absolute()}")
        return pd.DataFrame()
    
    all_data = []
    
    for excel_file in excel_files:
        print(f"\nProcessing: {excel_file.name}")
        
        # Determine port from filename
        port_name = "LA"
        if any(x in excel_file.name.lower() for x in ['longbeach', 'long_beach', 'lb', 'polb']):
            port_name = "LB"
        elif any(x in excel_file.name.lower() for x in ['losangeles', 'los_angeles', 'pola']):
            port_name = "LA"
        
        df = parse_manual_download(excel_file, port_name=port_name)
        
        if not df.empty:
            # Calculate stress indicators
            df = calculate_import_stress_index(df)
            all_data.append(df)
            print(f"  Loaded {len(df)} records for Port of {port_name}")
    
    if not all_data:
        return pd.DataFrame()
    
    combined = pd.concat(all_data, ignore_index=True)
    return combined


def normalize_and_save(df: pd.DataFrame) -> None:
    """Normalize port data and save to SQLite"""
    if df.empty:
        print("No port data to save")
        return
    
    # Create normalized dataframe
    df_normalized = pd.DataFrame({
        'id': df['port'].astype(str) + '_' + df['date'].astype(str),
        'date': df['date'],
        'port': df['port'],
        'teus': df.get('teus', 0),
        'teus_yoy_change': df.get('teus_yoy_change', 0),
        'teus_ma3': df.get('teus_ma3', 0),
        'teus_deviation': df.get('teus_deviation', 0),
        'supply_chain_stress': df.get('supply_chain_stress', 0),
        'timestamp': datetime.now()
    })
    
    # Clean numeric columns
    for col in ['teus', 'teus_yoy_change', 'teus_ma3', 'teus_deviation']:
        df_normalized[col] = pd.to_numeric(df_normalized[col], errors='coerce').fillna(0)
    
    # Drop duplicates
    df_normalized = df_normalized.drop_duplicates(subset=['id'])
    
    for col in ['date', 'timestamp']:
        if col in df_normalized.columns:
            df_normalized[col] = pd.to_datetime(df_normalized[col], errors='coerce').dt.tz_localize(None)

    def _to_py(val):
        if pd.isna(val):
            return None
        if isinstance(val, pd.Timestamp):
            return val.to_pydatetime()
        return val

    try:
        engine = create_engine(DB_URL)
        backend = engine.url.get_backend_name()

        with engine.begin() as conn:
            if backend == "sqlite":
                cols = [
                    'id', 'date', 'port', 'teus', 'teus_yoy_change', 'teus_ma3',
                    'teus_deviation', 'supply_chain_stress', 'timestamp'
                ]
                records = []
                for row in df_normalized.itertuples(index=False):
                    records.append({
                        'id': row.id,
                        'date': _to_py(row.date),
                        'port': row.port,
                        'teus': None if pd.isna(row.teus) else float(row.teus),
                        'teus_yoy_change': None if pd.isna(row.teus_yoy_change) else float(row.teus_yoy_change),
                        'teus_ma3': None if pd.isna(row.teus_ma3) else float(row.teus_ma3),
                        'teus_deviation': None if pd.isna(row.teus_deviation) else float(row.teus_deviation),
                        'supply_chain_stress': int(row.supply_chain_stress),
                        'timestamp': _to_py(row.timestamp)
                    })
                placeholders = ", ".join([f":{c}" for c in cols])
                update_clause = ", ".join([f"{c}=excluded.{c}" for c in cols if c != 'id'])
                stmt = text(
                    f"""
                    INSERT INTO port_la_lb_stats ({', '.join(cols)})
                    VALUES ({placeholders})
                    ON CONFLICT(id) DO UPDATE SET {update_clause}
                    """
                )
                conn.execute(stmt, records)
            else:
                df_normalized.to_sql(
                    'port_la_lb_stats',
                    conn,
                    if_exists='append',
                    index=False,
                    method='multi'
                )

        print(f"Saved {len(df_normalized)} port statistics records to database")
    except Exception as e:
        print(f"Error saving port data to database: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print(f"[{METIS_MODE}] Port of LA/LB Container Statistics")

    if not require_real_mode("Port Excel files"):
        exit(0)

    print("="*50)
    print("Processing port statistics from Excel files...")
    print("="*50)

    df = find_and_process_downloads()

    if not df.empty:
        print(f"\nTotal records loaded: {len(df)}")
        normalize_and_save(df)
    else:
        print("\nNo port data loaded")
