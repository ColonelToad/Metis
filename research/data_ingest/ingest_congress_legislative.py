"""
Congress.gov Legislative Data Ingestion
Fetches recent energy-related bills and amendments
API docs: https://api.congress.gov/
"""
import os
import sys
from pathlib import Path
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine

# Add project root for imports
sys.path.append(str(Path(__file__).resolve().parents[1]))
from research.common import runtime_config as rc

load_dotenv()
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY")
DB_URL = rc.get_db_url()

# Energy-related search terms for legislative tracking
ENERGY_KEYWORDS = [
    "natural gas",
    "lng",
    "pipeline",
    "energy",
    "infrastructure",
    "fossil",
    "methane",
    "gas",
    "oil",
    "climate"
]

def fetch_recent_bills(congress=118, limit=50):
    """
    Fetch recent bills from current Congress
    Congress 118 = 2023-2024, 119 = 2025-2026
    """
    if not rc.require_real_mode("Congress.gov API"):
        return pd.DataFrame()
    
    if not CONGRESS_API_KEY:
        print("Warning: CONGRESS_API_KEY not set in .env")
        return pd.DataFrame()
    
    url = f"https://api.congress.gov/v3/bill/{congress}"
    params = {
        'api_key': CONGRESS_API_KEY,
        'format': 'json',
        'limit': limit,
        'sort': 'updateDate desc'
    }
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        bills = data.get('bills', [])
        
        print(f"API returned {len(bills)} total bills")
        
        records = []
        for bill in bills:
            # Check if bill title/summary contains energy keywords
            title = bill.get('title', '').lower()
            bill_type = bill.get('type', '')
            bill_number = bill.get('number', '')
            
            # Filter for energy-related bills
            if any(keyword in title for keyword in ENERGY_KEYWORDS):
                records.append({
                    'congress': congress,
                    'bill_type': bill_type,
                    'bill_number': bill_number,
                    'title': bill.get('title', ''),
                    'origin_chamber': bill.get('originChamber', ''),
                    'latest_action_date': bill.get('latestAction', {}).get('actionDate'),
                    'latest_action_text': bill.get('latestAction', {}).get('text', ''),
                    'update_date': bill.get('updateDate'),
                    'url': bill.get('url', ''),
                    'timestamp': datetime.now()
                })
        
        if records:
            return pd.DataFrame(records)
        return pd.DataFrame()
    
    except Exception as e:
        print(f"Failed to fetch Congress bills: {e}")
        return pd.DataFrame()

def fetch_amendments(congress=118, limit=20):
    """Fetch recent amendments (often signal legislative urgency)"""
    if not rc.require_real_mode("Congress.gov Amendments API"):
        return pd.DataFrame()
    
    if not CONGRESS_API_KEY:
        return pd.DataFrame()
    
    url = f"https://api.congress.gov/v3/amendment/{congress}"
    params = {
        'api_key': CONGRESS_API_KEY,
        'format': 'json',
        'limit': limit,
        'sort': 'updateDate desc'
    }
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        amendments = data.get('amendments', [])
        
        records = []
        for amend in amendments:
            description = amend.get('description', '').lower()
            
            # Filter for energy-related amendments
            if any(keyword in description for keyword in ENERGY_KEYWORDS):
                records.append({
                    'congress': congress,
                    'amendment_number': amend.get('number', ''),
                    'amendment_type': amend.get('type', ''),
                    'description': amend.get('description', ''),
                    'purpose': amend.get('purpose', ''),
                    'latest_action_date': amend.get('latestAction', {}).get('actionDate'),
                    'latest_action_text': amend.get('latestAction', {}).get('text', ''),
                    'update_date': amend.get('updateDate'),
                    'timestamp': datetime.now()
                })
        
        if records:
            return pd.DataFrame(records)
        return pd.DataFrame()
    
    except Exception as e:
        print(f"Failed to fetch amendments: {e}")
        return pd.DataFrame()

if __name__ == "__main__":
    rc.log_mode("Congress.gov Legislative")
    
    # Fetch current Congress (119 = 2025-2026)
    print("Fetching energy-related bills from Congress.gov...")
    bills_df = fetch_recent_bills(congress=119, limit=100)
    
    if not bills_df.empty:
        print(f"Found {len(bills_df)} energy-related bills")
        
        # Save to database
        engine = create_engine(DB_URL)
        bills_df.to_sql('congress_bills', engine, if_exists='replace', index=False)
        
        print("Congressional bills saved to database")
        
        # Print summary
        print("\nRecent energy legislation:")
        for _, row in bills_df.head(5).iterrows():
            print(f"  {row['bill_type']}{row['bill_number']}: {row['title'][:80]}...")
    else:
        print("No energy-related bills found")
    
    print("\nFetching recent amendments...")
    amend_df = fetch_amendments(congress=119, limit=50)
    
    if not amend_df.empty:
        print(f"Found {len(amend_df)} energy-related amendments")
        
        engine = create_engine(DB_URL)
        amend_df.to_sql('congress_amendments', engine, if_exists='replace', index=False)
        
        print("Amendments saved to database")
    else:
        print("No energy-related amendments found")
