"""
Job Posting Data Ingestion (Labor Market Indicator)
Uses Adzuna API (free tier: 3000 calls/month)
Tracks energy sector hiring as leading indicator
"""
import os
import requests
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()
# Get free API key from: https://developer.adzuna.com/
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")  
ADZUNA_API_KEY = os.getenv("ADZUNA_API_KEY", "")
DB_URL = os.getenv("DB_URL", "postgresql://postgres:postgres@localhost:5432/metis")

# Energy sector keywords
ENERGY_KEYWORDS = [
    "natural gas",
    "energy trader",
    "petroleum engineer",
    "pipeline",
    "oil and gas",
    "renewable energy"
]

def fetch_job_postings(keyword, country="us"):
    """Fetch job postings for a given keyword"""
    if not ADZUNA_APP_ID or not ADZUNA_API_KEY:
        print("Warning: Adzuna API credentials not set. Get free key from https://developer.adzuna.com/")
        return pd.DataFrame()
    
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    params = {
        'app_id': ADZUNA_APP_ID,
        'app_key': ADZUNA_API_KEY,
        'what': keyword,
        'results_per_page': 50,
        'content-type': 'application/json'
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        
        data = response.json()
        results = data.get('results', [])
        
        if results:
            df = pd.DataFrame(results)
            df['keyword'] = keyword
            df['timestamp'] = datetime.now()
            return df[['timestamp', 'keyword', 'title', 'company', 'location', 'salary_min', 'salary_max', 'created']]
        
    except Exception as e:
        print(f"Error fetching jobs for '{keyword}': {e}")
    
    return pd.DataFrame()

if __name__ == "__main__":
    print("Fetching energy sector job postings...")
    
    all_jobs = []
    
    for keyword in ENERGY_KEYWORDS:
        df = fetch_job_postings(keyword)
        if len(df) > 0:
            all_jobs.append(df)
            print(f"Fetched {len(df)} jobs for '{keyword}'")
    
    if all_jobs:
        combined_df = pd.concat(all_jobs, ignore_index=True)
        
        # Save to database
        engine = create_engine(DB_URL)
        combined_df.to_sql('job_postings', engine, if_exists='append', index=False)
        
        print(f"Saved {len(combined_df)} total job postings to database")
    else:
        print("No job postings fetched. Set ADZUNA_APP_ID and ADZUNA_API_KEY in .env")
