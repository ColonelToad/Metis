"""
Maritime AIS Data Ingestion - Port-State Model

Tracks vessel composition at US LNG export terminals.
Instead of raw vessel positions, captures daily snapshots of:
- Terminal name
- Ship type (LNG tanker, general tanker, etc.)
- Count of vessels of that type
- Average speed/time-in-port metrics

This port-centric model provides early signals of supply constraints:
- Sudden drop in LNG tanker presence = capacity constraint
- Surge in support vessel activity = congestion
- Type distribution changes = market shifts

Integration with AISStream API for real-time vessel tracking.
Aggregates to daily snapshots for analytical signal generation.
"""

import os
import sys
from pathlib import Path
import json
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine
import logging
from typing import Dict, List, Tuple
from collections import defaultdict

# For WebSocket streaming (if using AISStream real-time)
try:
    import asyncio
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    logging.warning("websockets library not installed. Install via: pip install websockets")

# Add parent directory (research/) to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))
from common import runtime_config as rc

logger = logging.getLogger(__name__)

load_dotenv()
AISSTREAM_API_KEY = os.getenv("AIS_API_KEY", "")
DB_URL = rc.get_db_url()

# US Gulf Coast LNG export terminals
LNG_TERMINALS = {
    'Sabine Pass': {'lat_min': 29.65, 'lat_max': 29.80, 'lon_min': -93.95, 'lon_max': -93.75},
    'Cameron LNG': {'lat_min': 29.65, 'lat_max': 29.80, 'lon_min': -93.35, 'lon_max': -93.15},
    'Corpus Christi': {'lat_min': 27.65, 'lat_max': 27.85, 'lon_min': -97.35, 'lon_max': -97.15},
    'Cove Point': {'lat_min': 38.30, 'lat_max': 38.45, 'lon_min': -76.45, 'lon_max': -76.30},
    'Freeport': {'lat_min': 28.85, 'lat_max': 29.05, 'lon_min': -95.45, 'lon_max': -95.25},
}

# Ship type classifications (AIS standard codes)
SHIP_TYPES = {
    'LNG_CARRIER': (74, 84),  # AIS types 74 and 84 are LNG
    'TANKER_GENERAL': (80, 81, 82, 83, 85, 86, 87),  # General tanker types
    'TANKER_CRUDE': (80,),
    'TANKER_PRODUCT': (86,),
    'CARGO': (70, 71, 72, 73, 75, 76, 77, 78, 79),
    'TUG_SUPPORT': (31, 32, 52, 53, 54),
}


def is_at_terminal(lat: float, lon: float, terminal: Dict) -> bool:
    """Check if coordinates are within a terminal bounding box."""
    return (terminal['lat_min'] <= lat <= terminal['lat_max'] and
            terminal['lon_min'] <= lon <= terminal['lon_max'])


def find_terminal(lat: float, lon: float) -> str:
    """Find which terminal (if any) a vessel is at."""
    for name, coords in LNG_TERMINALS.items():
        if is_at_terminal(lat, lon, coords):
            return name
    return None


def classify_ship_type(ship_type_code: int) -> str:
    """Classify AIS ship type code into category."""
    # LNG carriers are top priority for tracking
    if ship_type_code in SHIP_TYPES['LNG_CARRIER']:
        return 'LNG_CARRIER'
    
    # General tankers
    if ship_type_code in SHIP_TYPES['TANKER_GENERAL']:
        return 'TANKER_GENERAL'
    
    # Tugs and support
    if ship_type_code in SHIP_TYPES['TUG_SUPPORT']:
        return 'TUG_SUPPORT'
    
    # Generic cargo/other
    return 'OTHER'


async def stream_ais_data(duration_minutes: int = 60) -> List[Dict]:
    """
    Connect to AISStream WebSocket and collect vessel data.
    
    Args:
        duration_minutes: How long to stream for (default 60 min)
    
    Returns:
        List of vessel records with position, type, and timestamp
    """
    if not HAS_WEBSOCKETS:
        logger.warning("websockets not installed, cannot stream real-time AIS")
        return []
    
    # Check if we should run in real mode
    if not rc.require_real_mode("AISStream WebSocket"):
        logger.info("[DEV MODE] Skipping AISStream WebSocket connection")
        return []
    
    if not AISSTREAM_API_KEY:
        logger.warning("AIS_API_KEY not set. Skipping AISStream WebSocket connection.")
        return []
    
    vessels_collected = []
    ws_url = "wss://stream.aisstream.io/v0/stream"
    
    try:
        async with websockets.connect(ws_url) as websocket:
            # Subscribe to vessel data at terminals
            subscription = {
                "APIKey": AISSTREAM_API_KEY,
                "BoundingBoxes": [
                    # Format: [lat_min, lon_min], [lat_max, lon_max] for each region
                    [[29.6, -94.0], [29.9, -93.7]],   # Sabine/Freeport
                    [[29.6, -93.4], [29.9, -93.1]],   # Cameron
                    [[27.6, -97.4], [27.9, -97.1]],   # Corpus Christi
                    [[38.2, -76.5], [38.5, -76.2]],   # Cove Point
                ],
                "FilterMessageTypes": ["ShipStaticData", "StandardClassBPositionReport"]
            }
            
            await websocket.send(json.dumps(subscription))
            logger.info(f"Subscribed to AISStream (will collect for {duration_minutes} minutes)")
            
            # Set timeout
            start_time = datetime.utcnow()
            end_time = start_time + timedelta(minutes=duration_minutes)
            
            while datetime.utcnow() < end_time:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    data = json.loads(message)
                    
                    # Parse message type
                    msg_type = data.get('MessageType')
                    msg_data = data.get('Message', {})
                    
                    # Extract vessel info from position report or static data
                    if msg_type == 'ShipStaticData':
                        vessel_data = msg_data.get('ShipStaticData', {})
                    elif msg_type == 'StandardClassBPositionReport':
                        vessel_data = msg_data.get('StandardClassBPositionReport', {})
                    else:
                        continue
                    
                    # Extract key fields
                    mmsi = vessel_data.get('UserID') or vessel_data.get('MMSI')
                    lat = vessel_data.get('Latitude')
                    lon = vessel_data.get('Longitude')
                    ship_type = vessel_data.get('ShipType')
                    speed = vessel_data.get('Sog', 0)
                    
                    # Validate data
                    if not all([mmsi, lat is not None, lon is not None, ship_type is not None]):
                        continue
                    
                    # Check if at a terminal
                    terminal = find_terminal(lat, lon)
                    if not terminal:
                        continue
                    
                    # Classify ship type
                    ship_class = classify_ship_type(int(ship_type))
                    
                    # Record vessel
                    vessels_collected.append({
                        'mmsi': str(mmsi),
                        'terminal': terminal,
                        'latitude': float(lat),
                        'longitude': float(lon),
                        'ship_type_code': int(ship_type),
                        'ship_type_class': ship_class,
                        'speed_knots': float(speed),
                        'timestamp': datetime.utcnow().isoformat()
                    })
                    
                    logger.debug(f"Captured {ship_class} at {terminal}")
                
                except asyncio.TimeoutError:
                    continue
                except json.JSONDecodeError:
                    logger.debug("Invalid JSON in WebSocket message")
                    continue
        
        logger.info(f"Collected {len(vessels_collected)} vessel observations")
        return vessels_collected
    
    except Exception as e:
        logger.error(f"WebSocket streaming error: {e}")
        return []


def aggregate_port_state(vessels: List[Dict]) -> pd.DataFrame:
    """
    Aggregate raw vessel observations into daily port snapshots.
    
    For each terminal-ship_type pair, calculate:
    - count: number of vessels
    - avg_speed: average speed
    - observation_window: time span of observations
    
    Returns:
        DataFrame with one row per terminal-type combination per day
    """
    if not vessels:
        return pd.DataFrame()
    
    # Group by terminal and ship type
    port_state = defaultdict(lambda: {'counts': defaultdict(int), 'speeds': [], 'timestamps': []})
    
    for v in vessels:
        terminal = v['terminal']
        ship_class = v['ship_type_class']
        
        port_state[terminal]['counts'][ship_class] += 1
        port_state[terminal]['speeds'].append(v['speed_knots'])
        port_state[terminal]['timestamps'].append(datetime.fromisoformat(v['timestamp']))
    
    # Convert to DataFrame
    rows = []
    for terminal, data in port_state.items():
        # Get observation window
        if data['timestamps']:
            start_time = min(data['timestamps'])
            end_time = max(data['timestamps'])
            obs_duration_hours = (end_time - start_time).total_seconds() / 3600
        else:
            obs_duration_hours = 0
        
        for ship_class, count in data['counts'].items():
            avg_speed = sum(data['speeds']) / len(data['speeds']) if data['speeds'] else 0
            
            rows.append({
                'date': datetime.utcnow().date(),
                'timestamp': datetime.utcnow(),
                'terminal': terminal,
                'ship_type_class': ship_class,
                'vessel_count': count,
                'avg_speed_knots': round(avg_speed, 2),
                'observation_duration_hours': round(obs_duration_hours, 2),
                'observation_count': len(data['speeds'])
            })
    
    return pd.DataFrame(rows)


def save_port_state(df: pd.DataFrame) -> bool:
    """Save daily port state snapshots to database."""
    if df.empty:
        logger.warning("No port state data to save")
        return False
    
    try:
        engine = create_engine(DB_URL)
        df.to_sql('maritime_ais_port_state', engine, if_exists='append', index=False)
        logger.info(f"Saved {len(df)} port state records to database")
        return True
    except Exception as e:
        logger.error(f"Error saving port state data: {e}")
        return False


def save_raw_vessels(vessels: List[Dict]) -> bool:
    """Save raw vessel observations for audit trail."""
    if not vessels:
        return False
    
    try:
        engine = create_engine(DB_URL)
        df = pd.DataFrame(vessels)
        df.to_sql('maritime_ais', engine, if_exists='append', index=False)
        logger.info(f"Saved {len(df)} raw vessel records to database (audit trail)")
        return True
    except Exception as e:
        logger.error(f"Error saving raw vessel data: {e}")
        return False


async def ingest_ais_maritime_async(duration_minutes: int = 60):
    """Main async ingestion function for maritime AIS data."""
    rc.log_mode("Maritime AIS")
    logger.info("Starting maritime AIS data ingestion (port-state model)...")
    
    # Collect raw vessel data from stream
    vessels = await stream_ais_data(duration_minutes=duration_minutes)
    
    if not vessels:
        logger.warning("No vessel data collected from AISStream")
        return pd.DataFrame()
    
    # Save raw data for audit
    save_raw_vessels(vessels)
    
    # Aggregate to port state
    port_state_df = aggregate_port_state(vessels)
    
    if not port_state_df.empty:
        save_port_state(port_state_df)
        logger.info(f"Port state aggregation complete. Shape: {port_state_df.shape}")
    
    return port_state_df


def ingest_ais_maritime_sync(duration_minutes: int = 2):
    """
    Synchronous wrapper for maritime AIS ingestion.
    
    Use this for scheduled tasks (e.g., Windows Task Scheduler).
    Connects to AISStream WebSocket and aggregates vessel data.
    
    Args:
        duration_minutes: Duration to stream for in minutes (default 2 for testing/quick runs)
                         Increase to 60 for production daily runs to capture more data
    """
    if not HAS_WEBSOCKETS:
        logger.error("websockets library required but not installed")
        logger.info("Install with: pip install websockets")
        return pd.DataFrame()
    
    # Run async function in synchronous context
    logger.info(f"Starting maritime AIS stream for {duration_minutes} minute(s)...")
    return asyncio.run(ingest_ais_maritime_async(duration_minutes=duration_minutes))


def main():
    """
    Entry point for scheduled ingestion (compatible with run_all_ingesters.py).
    Streams for 10 minutes to balance data collection with execution time.
    """
    return ingest_ais_maritime_sync(duration_minutes=10)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    if HAS_WEBSOCKETS:
        df = ingest_ais_maritime_sync()
        
        if not df.empty:
            print("\nPort state summary:")
            print(df.groupby(['terminal', 'ship_type_class'])['vessel_count'].sum().unstack(fill_value=0))
            print(f"\nTotal terminals observed: {df['terminal'].nunique()}")
            print(f"Total vessel type combinations: {len(df)}")
        else:
            print("No port state data captured")
    else:
        print("websockets library required. Install with: pip install websockets")
