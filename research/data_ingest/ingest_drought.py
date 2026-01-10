"""
US Drought Monitor Ingestion
Fetches weekly drought condition data from USDA
No API key required - open USDA data
"""
import os
import requests
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from io import StringIO
import time

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
METIS_MODE = os.getenv("METIS_MODE", "DEV")


def require_real_mode(source: str) -> bool:
    if METIS_MODE != "REAL":
        print(f"[DEV MODE] Skipping {source}")
        return False
    return True

STATS_URL = "https://usdmdataservices.unl.edu/api/USStatistics/GetDroughtSeverityStatisticsByArea?aoi=us&startdate=1/2/2000&enddate=1/1/2024&statisticsType=1"


def get_us_drought() -> pd.DataFrame:
    """Fetch national drought severity statistics using the provided fixed URL."""
    if not require_real_mode("US Drought Monitor API"):
        return pd.DataFrame()

    try:
        response = requests.get(STATS_URL, timeout=60)
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        try:
            data = response.json()
            df = pd.DataFrame(data)
        except ValueError:
            # Fallback to CSV content
            snippet = response.text[:200].replace("\n", " ")
            print(f"CSV response detected (status {response.status_code}), parsing... Snippet: {snippet}")
            df = pd.read_csv(StringIO(response.text))

        if df.empty:
            return pd.DataFrame()

        # Parse date field if present
        date_col = None
        for candidate in ["MapDate", "ValidStart", "ValidEnd"]:
            if candidate in df.columns:
                date_col = candidate
                df[candidate] = pd.to_datetime(df[candidate], errors="coerce")
                break

        if date_col is None:
            df["MapDate"] = pd.NaT
            date_col = "MapDate"

        # Assign state/area indicator
        if "StateAbbreviation" in df.columns:
            df["state"] = df["StateAbbreviation"].fillna("US")
        else:
            df["state"] = "US"

        # Normalize to expected columns
        if "MapDate" not in df.columns and date_col != "MapDate":
            df.rename(columns={date_col: "MapDate"}, inplace=True)

        return df

    except requests.exceptions.RequestException as e:
        print(f"Error fetching drought data: {e}")
        return pd.DataFrame()


def get_multi_state_drought() -> pd.DataFrame:
    """Wrapper to align with previous API; now fixed to US-only fetch."""
    print("Fetching drought data for US (fixed URL)...")
    return get_us_drought()


def calculate_drought_severity_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate weighted drought severity index from categorical percentages
    Weights: None=0, D0=1, D1=2, D2=3, D3=4, D4=5
    Scale: 0-5 (5 = most severe)
    """
    if df.empty:
        return df
    
    # Handle both 'None' and 'D0'-'D4' columns
    none_col = [c for c in df.columns if c.lower() == 'none']
    none_pct = df[none_col].iloc[:, 0] if none_col else 0
    
    df['drought_severity_index'] = (
        none_pct * 0 +
        df.get('D0', 0) * 1 +
        df.get('D1', 0) * 2 +
        df.get('D2', 0) * 3 +
        df.get('D3', 0) * 4 +
        df.get('D4', 0) * 5
    ) / 100  # Normalize to 0-5 scale
    
    return df


def normalize_and_save(df: pd.DataFrame) -> None:
    """Normalize drought data and save to SQLite"""
    if df.empty:
        print("No drought data to save")
        return
    
    # Ensure we have numeric columns
    numeric_cols = ['None', 'D0', 'D1', 'D2', 'D3', 'D4']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Calculate severity index
    df = calculate_drought_severity_index(df)
    
    # Create normalized dataframe
    df_normalized = pd.DataFrame({
        'id': df['state'].astype(str) + '_' + df['MapDate'].astype(str),
        'state': df['state'],
        'date': df['MapDate'],
        'drought_category_none': df.get('None', 0),
        'drought_category_d0': df.get('D0', 0),
        'drought_category_d1': df.get('D1', 0),
        'drought_category_d2': df.get('D2', 0),
        'drought_category_d3': df.get('D3', 0),
        'drought_category_d4': df.get('D4', 0),
        'drought_severity_index': df['drought_severity_index'],
        'timestamp': datetime.now()
    })
    
    # Drop duplicates
    df_normalized = df_normalized.drop_duplicates(subset=['id'])
    # Normalize datetimes for SQLite
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
                    'id', 'state', 'date', 'drought_category_none', 'drought_category_d0',
                    'drought_category_d1', 'drought_category_d2', 'drought_category_d3',
                    'drought_category_d4', 'drought_severity_index', 'timestamp'
                ]
                records = []
                for row in df_normalized.itertuples(index=False):
                    records.append({
                        'id': row.id,
                        'state': row.state,
                        'date': _to_py(row.date),
                        'drought_category_none': None if pd.isna(row.drought_category_none) else float(row.drought_category_none),
                        'drought_category_d0': None if pd.isna(row.drought_category_d0) else float(row.drought_category_d0),
                        'drought_category_d1': None if pd.isna(row.drought_category_d1) else float(row.drought_category_d1),
                        'drought_category_d2': None if pd.isna(row.drought_category_d2) else float(row.drought_category_d2),
                        'drought_category_d3': None if pd.isna(row.drought_category_d3) else float(row.drought_category_d3),
                        'drought_category_d4': None if pd.isna(row.drought_category_d4) else float(row.drought_category_d4),
                        'drought_severity_index': None if pd.isna(row.drought_severity_index) else float(row.drought_severity_index),
                        'timestamp': _to_py(row.timestamp)
                    })
                placeholders = ", ".join([f":{c}" for c in cols])
                update_clause = ", ".join([f"{c}=excluded.{c}" for c in cols if c != 'id'])
                stmt = text(
                    f"""
                    INSERT INTO drought_conditions ({', '.join(cols)})
                    VALUES ({placeholders})
                    ON CONFLICT(id) DO UPDATE SET {update_clause}
                    """
                )
                conn.execute(stmt, records)
            else:
                df_normalized.to_sql(
                    'drought_conditions',
                    conn,
                    if_exists='append',
                    index=False,
                    method='multi'
                )

        print(f"Saved {len(df_normalized)} drought records to database")
    except Exception as e:
        print(f"Error saving drought data to database: {e}")


if __name__ == "__main__":
    print(f"[{METIS_MODE}] US Drought Monitor")

    print("Fetching US Drought Monitor data...")

    df = get_multi_state_drought()

    if not df.empty:
        print(f"Fetched {len(df)} drought records")
        normalize_and_save(df)
    else:
        print("No drought data fetched")
