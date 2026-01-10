"""
FEMA Disaster Declarations Ingestion
Fetches federal emergency/disaster declarations
No API key required - open FEMA data
"""
import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import time

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
METIS_MODE = os.getenv("METIS_MODE", "DEV")


def require_real_mode(source: str) -> bool:
    if METIS_MODE != "REAL":
        print(f"[DEV MODE] Skipping {source}")
        return False
    return True

FEMA_API_URL = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"

def get_disaster_declarations(
    start_date: str,
    end_date: str,
    state: str = None,
    limit: int = 1000
) -> pd.DataFrame:
    """
    Fetch disaster declarations from OpenFEMA API
    
    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        state: Optional two-letter state code
        limit: Max records per request
    """
    if not require_real_mode("FEMA Disasters API"):
        return pd.DataFrame()
    
    filters = []
    if start_date:
        filters.append(f"declarationDate ge '{start_date}'")
    if end_date:
        filters.append(f"declarationDate le '{end_date}'")
    if state:
        filters.append(f"state eq '{state.upper()}'")
    
    params = {
        "$top": limit,
        "$skip": 0,
        "$orderby": "declarationDate desc"
    }
    
    if filters:
        params["$filter"] = " and ".join(filters)
    
    all_data = []
    
    while True:
        try:
            response = requests.get(FEMA_API_URL, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            records = data.get('DisasterDeclarationsSummaries', [])
            
            if not records:
                break
            
            all_data.extend(records)
            
            # Check if more data available
            metadata = data.get('metadata', {})
            total = metadata.get('count', 0)
            
            if len(all_data) >= total:
                break
            
            # Pagination
            params["$skip"] += limit
            time.sleep(0.5)  # Rate limiting
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching FEMA data: {e}")
            break
    
    if not all_data:
        return pd.DataFrame()
    
    df = pd.DataFrame(all_data)
    
    # Parse dates
    if 'declarationDate' in df.columns:
        df['declarationDate'] = pd.to_datetime(df['declarationDate'])
    if 'incidentBeginDate' in df.columns:
        df['incidentBeginDate'] = pd.to_datetime(df['incidentBeginDate'])
    if 'incidentEndDate' in df.columns:
        df['incidentEndDate'] = pd.to_datetime(df['incidentEndDate'])
    
    return df


def normalize_and_save(df: pd.DataFrame) -> None:
    """Normalize FEMA data and save to SQLite"""
    if df.empty:
        print("No FEMA disaster data to save")
        return
    
    # Rename and select key columns
    df_normalized = pd.DataFrame({
        'id': df['disasterNumber'].astype(str),
        'state': df['state'],
        'declaration_type': df.get('declarationType', ''),
        'incident_type': df.get('incidentType', ''),
        'declaration_date': df['declarationDate'],
        'incident_begin_date': df.get('incidentBeginDate'),
        'incident_end_date': df.get('incidentEndDate'),
        'title': df.get('declarationTitle', ''),
        'ihp_program_declared': df.get('ihpProgramDeclared', False),
        'iap_program_declared': df.get('iapProgramDeclared', False),
        'timestamp': datetime.now()
    })
    # Keep last occurrence per id to avoid duplicates inside the same batch
    df_normalized = df_normalized.drop_duplicates(subset=["id"], keep="last")
    # Normalize datetime values to naive Python datetimes for SQLite binding
    date_cols = ["declaration_date", "incident_begin_date", "incident_end_date", "timestamp"]
    for col in date_cols:
        if col in df_normalized.columns:
            df_normalized[col] = pd.to_datetime(df_normalized[col]).dt.tz_localize(None)

    def _to_py_dt(val):
        if pd.isna(val):
            return None
        if isinstance(val, pd.Timestamp):
            return val.to_pydatetime()
        return val
    
    try:
        engine = create_engine(DB_URL)
        backend = engine.url.get_backend_name()

        with engine.begin() as conn:
            # Clear old data to start fresh
            conn.execute(text("DELETE FROM fema_disasters"))

            if backend == "sqlite":
                cols = [
                    "id",
                    "state",
                    "declaration_type",
                    "incident_type",
                    "declaration_date",
                    "incident_begin_date",
                    "incident_end_date",
                    "title",
                    "ihp_program_declared",
                    "iap_program_declared",
                    "timestamp",
                ]
                records = []
                for row in df_normalized.itertuples(index=False):
                    records.append({
                        "id": row.id,
                        "state": row.state,
                        "declaration_type": row.declaration_type,
                        "incident_type": row.incident_type,
                        "declaration_date": _to_py_dt(row.declaration_date),
                        "incident_begin_date": _to_py_dt(row.incident_begin_date),
                        "incident_end_date": _to_py_dt(row.incident_end_date),
                        "title": row.title,
                        "ihp_program_declared": bool(row.ihp_program_declared),
                        "iap_program_declared": bool(row.iap_program_declared),
                        "timestamp": _to_py_dt(row.timestamp),
                    })
                placeholders = ", ".join([f":{c}" for c in cols])
                update_clause = ", ".join(
                    [f"{c}=excluded.{c}" for c in cols if c != "id"]
                )
                stmt = text(
                    f"""
                    INSERT INTO fema_disasters ({', '.join(cols)})
                    VALUES ({placeholders})
                    ON CONFLICT(id) DO UPDATE SET {update_clause}
                    """
                )
                conn.execute(stmt, records)
            else:
                # Fallback for other backends: append; relies on unique constraint to update manually if needed
                df_normalized.to_sql(
                    "fema_disasters",
                    conn,
                    if_exists="append",
                    index=False,
                    method="multi",
                )

        print(f"Saved {len(df_normalized)} FEMA disaster records to database")
    except Exception as e:
        print(f"Error saving FEMA data to database: {e}")


if __name__ == "__main__":
    print(f"[{METIS_MODE}] FEMA Disasters")

    # Fetch last 2 years of disasters
    end_date = datetime.now()
    start_date = end_date - timedelta(days=730)

    print("Fetching FEMA disaster declarations...")

    df = get_disaster_declarations(
        start_date.strftime('%Y-%m-%d'),
        end_date.strftime('%Y-%m-%d')
    )

    if not df.empty:
        print(f"Fetched {len(df)} FEMA disaster declarations")
        normalize_and_save(df)
    else:
        print("No FEMA data fetched")
