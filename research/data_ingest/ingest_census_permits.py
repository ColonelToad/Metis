"""
Census Building Permits Ingestion
Parses building permit data from downloaded Excel files
Files: permits_cust_old.xlsx (1995-2019), permitsbyusreg_cust.xls (2019-2025)
"""
import os
from pathlib import Path
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import time

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
METIS_MODE = os.getenv("METIS_MODE", "DEV")

# Excel files in data/census/
DATA_DIR = Path("data/census")
OLD_FILE = DATA_DIR / "permits_cust_old.xlsx"
RECENT_FILE = DATA_DIR / "permitsbyusreg_cust.xls"


def require_real_mode(source: str) -> bool:
    if METIS_MODE != "REAL":
        print(f"[DEV MODE] Skipping {source}")
        return False
    return True


def parse_old_file(file_path: Path) -> pd.DataFrame:
    """
    Parse permits_cust_old.xlsx (1995-2019)
    Multi-row header with Year and US Total columns
    """
    if not file_path.exists():
        print(f"File not found: {file_path}")
        return pd.DataFrame()
    
    try:
        # Skip first 4 rows, use row 5 as partial header
        df = pd.read_excel(file_path, skiprows=4)
        
        # First column is Year, second is US Total
        df = df.rename(columns={df.columns[0]: 'year', df.columns[1]: 'total'})
        
        # Keep only year and total columns, filter valid years
        df = df[['year', 'total']].copy()
        df['year'] = pd.to_numeric(df['year'], errors='coerce')
        df = df.dropna(subset=['year'])
        df = df[df['year'] >= 1995]  # Filter to 1995+
        
        # Create date (annual data, use Jan 1)
        df['date'] = pd.to_datetime(df['year'].astype(int).astype(str) + '-01-01', errors='coerce')
        df['permit_count'] = pd.to_numeric(df['total'], errors='coerce')
        
        print(f"Loaded {len(df)} records from old file (1995-2019)")
        return df
        
    except Exception as e:
        print(f"Error parsing old file: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def parse_recent_file(file_path: Path) -> pd.DataFrame:
    """
    Parse permitsbyusreg_cust.xls (2019-2025)
    Similar structure to old file (annual totals, by region and US)
    """
    if not file_path.exists():
        print(f"File not found: {file_path}")
        return pd.DataFrame()
    
    try:
        # Header row at index 4 contains 'Year²' and 'United States'
        df = pd.read_excel(file_path, header=4)
        df.columns = [str(c).strip("'") for c in df.columns]
        if 'Year²' not in df.columns or 'United States' not in df.columns:
            print("Unexpected columns in recent file")
            return pd.DataFrame()

        df = df.rename(columns={'Year²': 'year', 'United States': 'total'})
        df = df[['year', 'total']].copy()
        df['year'] = pd.to_numeric(df['year'], errors='coerce')
        df = df.dropna(subset=['year'])
        df = df[df['year'] >= 2019]

        df['date'] = pd.to_datetime(df['year'].astype(int).astype(str) + '-01-01', errors='coerce')
        df['permit_count'] = pd.to_numeric(df['total'], errors='coerce')

        df = df.dropna(subset=['date'])
        print(f"Loaded {len(df)} records from recent file (2019-2025)")
        return df

    except Exception as e:
        print(f"Error parsing recent file: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def get_permits_all() -> pd.DataFrame:
    """Load and combine both Excel files"""
    if not require_real_mode("Census Building Permits Excel"):
        return pd.DataFrame()
    
    old_df = parse_old_file(OLD_FILE)
    recent_df = parse_recent_file(RECENT_FILE)
    
    all_data = []
    if not old_df.empty:
        all_data.append(old_df)
    if not recent_df.empty:
        all_data.append(recent_df)
    
    if not all_data:
        return pd.DataFrame()
    
    combined = pd.concat(all_data, ignore_index=True)
    
    # Remove duplicates (2019 overlap)
    if 'date' in combined.columns:
        combined = combined.sort_values('date').drop_duplicates(subset=['date'], keep='last')
    
    return combined


def normalize_and_save(df: pd.DataFrame) -> None:
    """Normalize census permit data and save to SQLite"""
    if df.empty:
        print("No Census permit data to save")
        return
    
    # Ensure required columns exist
    if 'date' not in df.columns:
        print("Error: 'date' column missing from data")
        return
    
    # Try to extract state/region info
    state_col = None
    for col in ['state', 'region', 'state_code', 'state_abbr']:
        if col in df.columns:
            state_col = col
            break
    
    if state_col is None:
        df['state'] = 'US'  # National aggregate
    else:
        df['state'] = df[state_col]
    
    # Extract permit metrics
    permit_count_col = None
    for col in ['permit', 'permit_count', 'permits', 'units']:
        if col in df.columns:
            permit_count_col = col
            break
    
    permit_val_col = None
    for col in ['permit_val', 'permit_value', 'valuation', 'value']:
        if col in df.columns:
            permit_val_col = col
            break
    
    df_normalized = pd.DataFrame({
        'id': df['state'].astype(str) + '_' + df['date'].astype(str),
        'date': df['date'],
        'state': df['state'],
        'county': df.get('county', ''),
        'permit_count': df[permit_count_col] if permit_count_col else 0,
        'permit_valuation': df[permit_val_col] if permit_val_col else 0,
        'units_issued': df.get('units_issued', df.get('units', 0)),
        'timestamp': datetime.now()
    })
    
    # Clean numeric columns
    for col in ['permit_count', 'permit_valuation', 'units_issued']:
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
                    'id', 'date', 'state', 'county', 'permit_count', 'permit_valuation',
                    'units_issued', 'timestamp'
                ]
                records = []
                for row in df_normalized.itertuples(index=False):
                    records.append({
                        'id': row.id,
                        'date': _to_py(row.date),
                        'state': row.state,
                        'county': row.county,
                        'permit_count': None if pd.isna(row.permit_count) else int(row.permit_count),
                        'permit_valuation': None if pd.isna(row.permit_valuation) else float(row.permit_valuation),
                        'units_issued': None if pd.isna(row.units_issued) else int(row.units_issued),
                        'timestamp': _to_py(row.timestamp)
                    })
                placeholders = ", ".join([f":{c}" for c in cols])
                update_clause = ", ".join([f"{c}=excluded.{c}" for c in cols if c != 'id'])
                stmt = text(
                    f"""
                    INSERT INTO census_building_permits ({', '.join(cols)})
                    VALUES ({placeholders})
                    ON CONFLICT(id) DO UPDATE SET {update_clause}
                    """
                )
                conn.execute(stmt, records)
            else:
                df_normalized.to_sql(
                    'census_building_permits',
                    conn,
                    if_exists='append',
                    index=False,
                    method='multi'
                )

        print(f"Saved {len(df_normalized)} Census permit records to database")
    except Exception as e:
        print(f"Error saving Census permit data to database: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print(f"[{METIS_MODE}] Census Building Permits (Excel)")

    print("Loading Census building permits from Excel files...")
    print(f"  - {OLD_FILE}")
    print(f"  - {RECENT_FILE}")

    df = get_permits_all()

    if not df.empty:
        print(f"Loaded {len(df)} total Census permit records")
        normalize_and_save(df)
    else:
        print("No Census permit data loaded")
