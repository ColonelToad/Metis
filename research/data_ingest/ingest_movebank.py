"""
Movebank Wildlife Tracking Ingestion
Tracks migratory birds and animals as early signals for:
- Weather disruptions (storms, extreme cold)
- Supply chain disruptions (mass wildlife movement before natural disasters)
API docs: https://github.com/movebank/movebank-api-doc
"""
import os
import sys
from pathlib import Path
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine
from requests.auth import HTTPBasicAuth

# Add project root for imports
sys.path.append(str(Path(__file__).resolve().parents[1]))
from research.common import runtime_config as rc

load_dotenv()
MOVEBANK_USERNAME = os.getenv("MOVEBANK_USERNAME")
MOVEBANK_PASSWORD = os.getenv("MOVEBANK_PASSWORD")
DB_URL = rc.get_db_url()

# Study IDs for relevant species in US energy corridors
# Using publicly accessible studies with active tracking
STUDY_IDS = {
    # Large deployment studies with weather/climate correlation potential
    '2943485': 'North American Songbird Migration',
    '446575': 'Waterfowl Migration Ecology',
    '1531481854': 'Raptor Movement Tracking',
}

def fetch_movebank_events(study_id, study_name, days_back=90):
    """
    Fetch recent animal movement events from Movebank
    Returns location data for tracking sudden mass movements
    (Default: 90 days to ensure data availability)
    """
    if not rc.require_real_mode("Movebank API"):
        return pd.DataFrame()
    
    if not MOVEBANK_USERNAME or not MOVEBANK_PASSWORD:
        print("Warning: MOVEBANK credentials not set in .env")
        return pd.DataFrame()
    
    # Movebank uses Basic Auth
    auth = HTTPBasicAuth(MOVEBANK_USERNAME, MOVEBANK_PASSWORD)
    
    # Calculate timestamp range (Unix milliseconds)
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days_back)
    
    # Movebank expects timestamps in milliseconds since epoch
    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)
    
    url = "https://www.movebank.org/movebank/service/direct-read"
    params = {
        'entity_type': 'event',
        'study_id': study_id,
        'timestamp_start': start_ms,
        'timestamp_end': end_ms,
        'sensor_type_id': 'gps',  # GPS only (most accurate)
        'attributes': 'individual_local_identifier,timestamp,location_long,location_lat,ground_speed,heading'
    }
    
    try:
        response = requests.get(url, params=params, auth=auth, timeout=30)
        response.raise_for_status()
        
        # Debug: check response
        if len(response.text) < 100:
            print(f"  Empty or very short response for {study_name}")
            return pd.DataFrame()
        
        # Check if response is actually CSV (not HTML error page)
        content_type = response.headers.get('Content-Type', '')
        if 'text/csv' not in content_type and 'text/plain' not in content_type:
            print(f"  Unexpected content type for {study_name}: {content_type}")
            return pd.DataFrame()
        
        # Movebank returns CSV
        from io import StringIO
        df = pd.read_csv(StringIO(response.text))
        
        if df.empty:
            print(f"  No data returned for {study_name}")
            return pd.DataFrame()
        
        # Convert timestamp from ms to datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['study_id'] = study_id
        df['study_name'] = study_name
        df['fetch_time'] = datetime.now()
        
        # Rename columns for consistency
        df = df.rename(columns={
            'individual_local_identifier': 'animal_id',
            'location_long': 'longitude',
            'location_lat': 'latitude'
        })
        
        return df[['study_id', 'study_name', 'animal_id', 'timestamp', 'latitude', 'longitude', 'ground_speed', 'heading', 'fetch_time']]
    
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            print(f"  Access denied for study {study_id} (may require permission)")
        elif e.response.status_code == 401:
            print(f"  Authentication failed - check MOVEBANK credentials")
        else:
            print(f"  HTTP error for {study_name}: {e}")
        return pd.DataFrame()
    
    except pd.errors.ParserError as e:
        print(f"  CSV parsing error for {study_name} (likely no data or restricted access)")
        return pd.DataFrame()
    
    except Exception as e:
        print(f"  Failed to fetch {study_name}: {e}")
        return pd.DataFrame()

def compute_anomaly_metrics(df):
    """
    Compute movement anomalies:
    - Sudden speed increases (fleeing behavior)
    - Coordinated directional changes (mass migration shift)
    - Density changes (clustering/dispersal)
    """
    if df.empty:
        return pd.DataFrame()
    
    # Group by study and compute aggregates
    metrics = df.groupby(['study_id', 'study_name']).agg({
        'animal_id': 'count',
        'ground_speed': ['mean', 'max', 'std'],
        'heading': 'std',  # High std = coordinated direction change
    }).reset_index()
    
    metrics.columns = ['study_id', 'study_name', 'event_count', 'avg_speed', 'max_speed', 'speed_std', 'heading_std']
    metrics['timestamp'] = datetime.now()
    
    return metrics

if __name__ == "__main__":
    rc.log_mode("Movebank Wildlife")
    
    print("Fetching wildlife tracking data from Movebank...")
    
    all_events = []
    
    for study_id, study_name in STUDY_IDS.items():
        print(f"\nFetching {study_name} (study {study_id})...")
        df = fetch_movebank_events(study_id, study_name, days_back=90)
        
        if not df.empty:
            all_events.append(df)
            print(f"  Fetched {len(df)} movement events from {df['animal_id'].nunique()} individuals")
    
    if all_events:
        combined_df = pd.concat(all_events, ignore_index=True)
        
        # Save raw events
        engine = create_engine(DB_URL)
        combined_df.to_sql('movebank_events', engine, if_exists='append', index=False)
        
        print(f"\nSaved {len(combined_df)} total wildlife movement events")
        
        # Compute and save anomaly metrics
        metrics_df = compute_anomaly_metrics(combined_df)
        if not metrics_df.empty:
            metrics_df.to_sql('movebank_metrics', engine, if_exists='append', index=False)
            print(f"Saved movement metrics for {len(metrics_df)} studies")
            
            # Print summary
            print("\nMovement summary:")
            for _, row in metrics_df.iterrows():
                print(f"  {row['study_name']}: {row['event_count']} events, avg speed {row['avg_speed']:.1f} m/s")
    else:
        print("No wildlife tracking data fetched")
