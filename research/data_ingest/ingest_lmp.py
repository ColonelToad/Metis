"""
Grid LMP Data Ingestion using gridstatus
Fetches real-time and day-ahead LMP for major ISOs
"""
import os
import sys
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta
from gridstatus import PJM, CAISO, Ercot, MISO
from sqlalchemy import create_engine
from dotenv import load_dotenv

# Add project root for imports
sys.path.append(str(Path(__file__).resolve().parents[1]))
from research.common import runtime_config as rc

load_dotenv()
DB_URL = rc.get_db_url()

def fetch_pjm_lmp(start_date, end_date):
    """Fetch PJM real-time LMP data"""
    if not rc.require_real_mode("PJM LMP API"):
        return pd.DataFrame()
    pjm = PJM()
    
    df = pjm.get_lmp(
        date=start_date,
        end=end_date,
        market="REAL_TIME_5_MIN"
    )
    
    df['iso'] = 'PJM'
    return df

def fetch_ercot_lmp(start_date, end_date):
    """Fetch ERCOT real-time LMP data"""
    if not rc.require_real_mode("ERCOT LMP API"):
        return pd.DataFrame()
    ercot = Ercot()
    
    df = ercot.get_lmp(
        date=start_date,
        end=end_date,
        market="REAL_TIME_15_MIN"
    )
    
    df['iso'] = 'ERCOT'
    return df

def fetch_caiso_lmp(start_date, end_date):
    """Fetch CAISO real-time LMP data"""
    if not rc.require_real_mode("CAISO LMP API"):
        return pd.DataFrame()
    caiso = CAISO()
    
    df = caiso.get_lmp(
        date=start_date,
        end=end_date,
        market="REAL_TIME_5_MIN"
    )
    
    df['iso'] = 'CAISO'
    return df

if __name__ == "__main__":
    rc.log_mode("LMP")
    # Fetch last 7 days
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)
    
    print("Fetching LMP data from multiple ISOs...")
    
    dfs = []
    
    try:
        pjm_df = fetch_pjm_lmp(start_date, end_date)
        print(f"Fetched {len(pjm_df)} PJM LMP records")
        dfs.append(pjm_df)
    except Exception as e:
        print(f"PJM fetch failed: {e}")
    
    try:
        ercot_df = fetch_ercot_lmp(start_date, end_date)
        print(f"Fetched {len(ercot_df)} ERCOT LMP records")
        dfs.append(ercot_df)
    except Exception as e:
        print(f"ERCOT fetch failed: {e}")
    
    try:
        caiso_df = fetch_caiso_lmp(start_date, end_date)
        print(f"Fetched {len(caiso_df)} CAISO LMP records")
        dfs.append(caiso_df)
    except Exception as e:
        print(f"CAISO fetch failed: {e}")
    
    if dfs:
        combined_df = pd.concat(dfs, ignore_index=True)
        
        # Standardize columns
        combined_df = combined_df.rename(columns={
            'Time': 'timestamp',
            'LMP': 'lmp',
            'Location': 'node_id'
        })
        
        # Save to database
        engine = create_engine(DB_URL)
        combined_df.to_sql('grid_lmp', engine, if_exists='append', index=False)
        
        print(f"Saved {len(combined_df)} total LMP records to database")
    else:
        print("No LMP data fetched")
