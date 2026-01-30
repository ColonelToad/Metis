"""
FRED API Test - Building Permits
Tests connection to FRED API and fetches national building permit data.
"""
import os
import requests
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
FRED_API_KEY = os.getenv("FRED_API_KEY", "")

def test_fred_permits():
    """
    Test FRED API connection with building permits series.
    
    Series ID: PERMIT (New Privately-Owned Housing Units Authorized in Permit-Issuing Places)
    This is monthly, national-level data from Census Bureau.
    """
    if not FRED_API_KEY:
        print("[ERROR] Missing FRED_API_KEY in environment variables")
        return None
    
    # FRED API endpoint for series observations
    url = "https://api.stlouisfed.org/fred/series/observations"
    
    params = {
        "series_id": "PERMIT",  # National building permits
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": "2015-01-01",  # Last 10 years
    }
    
    try:
        print(f"[FRED] Testing API connection...")
        print(f"[FRED] Endpoint: {url}")
        print(f"[FRED] Series: PERMIT (Building Permits)")
        
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # Check for errors in response
        if "error_code" in data:
            print(f"[ERROR] FRED API error: {data.get('error_message', 'Unknown error')}")
            return None
        
        # Parse observations
        observations = data.get("observations", [])
        
        if not observations:
            print("[ERROR] No data returned from FRED")
            return None
        
        # Convert to DataFrame
        df = pd.DataFrame(observations)
        df = df[['date', 'value']].copy()
        df['date'] = pd.to_datetime(df['date'])
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        df = df.dropna()
        df.columns = ['date', 'permit_count']
        
        # Display results
        print(f"\n[SUCCESS] ✓ FRED API connection successful!")
        print(f"[SUCCESS] ✓ Retrieved {len(df)} monthly records")
        print(f"\nLatest 5 records:")
        print(df.tail(5).to_string(index=False))
        
        # Summary stats
        latest = df.iloc[-1]
        print(f"\n[SUMMARY] Latest data point:")
        print(f"  Date: {latest['date'].strftime('%Y-%m')}")
        print(f"  Building Permits: {latest['permit_count']:,.0f} units")
        
        return df
        
    except requests.exceptions.HTTPError as e:
        print(f"[ERROR] HTTP error: {e}")
        if e.response.status_code == 400:
            print("[ERROR] Possible invalid API key or parameters")
        elif e.response.status_code == 429:
            print("[ERROR] Rate limit exceeded")
        return None
    except Exception as e:
        print(f"[ERROR] Request failed: {e}")
        return None


if __name__ == "__main__":
    print("=" * 60)
    print("FRED API Building Permits Test")
    print("=" * 60)
    test_fred_permits()
