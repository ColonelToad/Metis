"""
Maritime AIS Data Ingestion (Supply Chain Indicator)
Uses MarineTraffic free tier API
Tracks LNG tanker movements as supply indicator
"""
import os
import requests
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()
# Get free API key from: https://www.marinetraffic.com/en/ais-api-services
MARINETRAFFIC_API_KEY = os.getenv("MARINETRAFFIC_API_KEY", "")
DB_URL = os.getenv("DB_URL", "postgresql://postgres:postgres@localhost:5432/metis")

# Key LNG export terminals (major US ports)
LNG_TERMINALS = {
    'Sabine Pass': {'lat': 29.7289, 'lon': -93.8767},
    'Cove Point': {'lat': 38.3847, 'lon': -76.3814},
    'Corpus Christi': {'lat': 27.8006, 'lon': -97.3964},
    'Cameron': {'lat': 29.7657, 'lon': -93.3271},
    'Freeport': {'lat': 28.9433, 'lon': -95.3094},
}

def fetch_vessels_near_terminal(terminal_name, coords, radius_nm=5):
    """Fetch vessels near an LNG terminal"""
    if not MARINETRAFFIC_API_KEY:
        print("Warning: MarineTraffic API key not set. Get free key from marinetraffic.com")
        return pd.DataFrame()
    
    url = "https://services.marinetraffic.com/api/exportvessels/v:8"
    params = {
        'v': '8',
        'key': MARINETRAFFIC_API_KEY,
        'protocol': 'json',
        'minlat': coords['lat'] - (radius_nm / 60),
        'maxlat': coords['lat'] + (radius_nm / 60),
        'minlon': coords['lon'] - (radius_nm / 60),
        'maxlon': coords['lon'] + (radius_nm / 60),
        'shiptype': '74',  # LNG tankers
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        
        data = response.json()
        
        if data and len(data) > 0:
            df = pd.DataFrame(data)
            df['terminal'] = terminal_name
            df['timestamp'] = datetime.now()
            return df[['timestamp', 'terminal', 'SHIPNAME', 'FLAG', 'SPEED', 'COURSE', 'LAT', 'LON', 'DESTINATION']]
        
    except Exception as e:
        print(f"Error fetching vessels near {terminal_name}: {e}")
    
    return pd.DataFrame()

if __name__ == "__main__":
    print("Fetching LNG tanker positions near US export terminals...")
    
    all_vessels = []
    
    for terminal_name, coords in LNG_TERMINALS.items():
        df = fetch_vessels_near_terminal(terminal_name, coords)
        if len(df) > 0:
            all_vessels.append(df)
            print(f"Found {len(df)} vessels near {terminal_name}")
    
    if all_vessels:
        combined_df = pd.concat(all_vessels, ignore_index=True)
        
        # Save to database
        engine = create_engine(DB_URL)
        combined_df.to_sql('maritime_ais', engine, if_exists='append', index=False)
        
        print(f"Saved {len(combined_df)} vessel positions to database")
    else:
        print("No vessel data fetched. Set MARINETRAFFIC_API_KEY in .env or use free tier.")
