"""
TomTom Traffic Data Ingestion
Fetches real-time and historical traffic speeds near key energy infrastructure
"""
import os
import sys
from pathlib import Path
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine
import json

# Add project root for imports
sys.path.append(str(Path(__file__).resolve().parents[1]))
from research.common import runtime_config as rc

load_dotenv()
TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY")
DB_URL = rc.get_db_url()

# Major LNG terminals and pipeline hubs in US
ENERGY_NODES = {
    'Sabine Pass LNG': {'lat': 29.7289, 'lon': -93.8767, 'region': 'Gulf Coast'},
    'Corpus Christi LNG': {'lat': 27.8006, 'lon': -97.3964, 'region': 'Gulf Coast'},
    'Freeport LNG': {'lat': 28.9433, 'lon': -95.3094, 'region': 'Gulf Coast'},
    'Cameron LNG': {'lat': 29.7657, 'lon': -93.3271, 'region': 'Gulf Coast'},
    'Cove Point LNG': {'lat': 38.3847, 'lon': -76.3814, 'region': 'Mid-Atlantic'},
    'Permian Basin Hub': {'lat': 32.1693, 'lon': -102.0200, 'region': 'Permian'},
    'Marcellus Hub (PA)': {'lat': 41.0082, 'lon': -76.8754, 'region': 'Appalachia'},
    'Chicago Trading Hub': {'lat': 41.8781, 'lon': -87.6298, 'region': 'Midwest'},
}

def fetch_traffic_near_node(node_name, coords, radius_km=20):
    """
    Fetch current traffic speeds using TomTom Flow API
    Returns average speeds and congestion levels in radius around node
    """
    if not rc.require_real_mode("TomTom Traffic API"):
        return None
    if not TOMTOM_API_KEY:
        print("Warning: TOMTOM_API_KEY not set in .env")
        return None
    
    # Use Flow API to get traffic speeds
    url = "https://api.tomtom.com/traffic/services/4/flowSegmentData/json"
    
    params = {
        'key': TOMTOM_API_KEY,
        'point': f"{coords['lat']},{coords['lon']}",
        'thickness': 10,  # 10km radius
        'minZoom': 10,
        'maxZoom': 18,
        'unit': 'KMPH'
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if 'flowSegmentData' in data:
            segments = data['flowSegmentData']
            
            # Aggregate traffic metrics
            speeds = [s.get('currentSpeed', 0) for s in segments]
            free_flows = [s.get('freeFlowSpeed', 0) for s in segments]
            
            if speeds:
                avg_speed = sum(speeds) / len(speeds)
                avg_free_flow = sum(free_flows) / len(free_flows)
                congestion_level = 1.0 - (avg_speed / avg_free_flow) if avg_free_flow > 0 else 0
                
                return {
                    'timestamp': datetime.now(),
                    'node': node_name,
                    'region': coords['region'],
                    'lat': coords['lat'],
                    'lon': coords['lon'],
                    'avg_speed_kmph': avg_speed,
                    'free_flow_speed_kmph': avg_free_flow,
                    'congestion_level': congestion_level,
                    'num_segments': len(segments),
                }
        
    except Exception as e:
        print(f"Error fetching traffic for {node_name}: {e}")
    
    return None

def fetch_historical_traffic_availability():
    """
    Check TomTom historical traffic endpoints
    Note: Historical data requires premium subscription
    Returns info on how to structure future historical requests
    """
    print("TomTom historical traffic requires premium subscription.")
    print("Free tier supports real-time speeds only.")
    print("\nFor historical analysis, consider:")
    print("- Aggregate real-time snapshots into daily/hourly summaries")
    print("- Use PeMS (CA) or state DOT APIs for historical speeds")
    print("- Compute trend features from real-time snapshots over time")

if __name__ == "__main__":
    rc.log_mode("TomTom")
    print("Fetching real-time traffic data from TomTom...")
    
    all_traffic = []
    
    for node_name, coords in ENERGY_NODES.items():
        traffic_data = fetch_traffic_near_node(node_name, coords)
        
        if traffic_data:
            all_traffic.append(traffic_data)
            print(f"{node_name:30} Congestion: {traffic_data['congestion_level']:.2%} | Speed: {traffic_data['avg_speed_kmph']:.1f} km/h")
        else:
            print(f"{node_name:30} [Failed to fetch]")
    
    if all_traffic:
        df = pd.DataFrame(all_traffic)
        
        # Save to database
        engine = create_engine(DB_URL)
        df.to_sql('tomtom_traffic', engine, if_exists='append', index=False)
        
        print(f"\nSaved {len(df)} traffic readings to database")
        
        # Also save as Parquet for analysis
        os.makedirs('../data/processed', exist_ok=True)
        df.to_parquet(f'../data/processed/tomtom_traffic_{datetime.now().strftime("%Y%m%d_%H%M%S")}.parquet')
        print(f"Saved traffic snapshot to Parquet")
    else:
        print("No traffic data fetched")
    
    # Print note on historical data
    fetch_historical_traffic_availability()
