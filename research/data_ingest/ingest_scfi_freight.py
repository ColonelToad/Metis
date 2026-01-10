"""
SCFI Shipping Rates Ingestion
Shanghai Containerized Freight Index - scrapes current rates
Graceful failure mode - if scraping fails, just log and continue
No API key required, but relies on web scraping (fragile)
"""
import os
import requests
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine
import traceback

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
METIS_MODE = os.getenv("METIS_MODE", "DEV")


def require_real_mode(source: str) -> bool:
    if METIS_MODE != "REAL":
        print(f"[DEV MODE] Skipping {source}")
        return False
    return True

SCFI_URL = "http://en.sse.net.cn/indices/scfinew.jsp"


def scrape_current_scfi() -> pd.DataFrame:
    """
    Scrape current week SCFI rates from SSE website
    Gracefully handles failures - returns empty DataFrame if scraping fails
    """
    if not require_real_mode("SCFI Freight Rates"):
        return pd.DataFrame()
    
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("Warning: BeautifulSoup not installed. Install with: pip install beautifulsoup4")
        return pd.DataFrame()
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(SCFI_URL, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find SCFI data table - try multiple selectors in case structure changes
        table = None
        selectors = [
            ('table', {'class': 'data_table'}),
            ('table', {'class': 'scfi_table'}),
            ('table', {'id': 'scfi_data'}),
        ]
        
        for tag, attrs in selectors:
            table = soup.find(tag, attrs)
            if table:
                print(f"Found SCFI table with selector: {tag} {attrs}")
                break
        
        # Fallback: get first table if no specific selector worked
        if not table:
            tables = soup.find_all('table')
            if tables:
                table = tables[0]
                print("Using first table found on page")
        
        if not table:
            print("Warning: Could not find SCFI data table on page")
            return pd.DataFrame()
        
        # Parse table
        rows = []
        for tr in table.find_all('tr')[1:]:  # Skip header
            cells = tr.find_all('td')
            if len(cells) >= 3:
                try:
                    row = {
                        'route': cells[0].text.strip(),
                        'current_rate': float(cells[1].text.strip()),
                        'week_over_week_change': cells[2].text.strip()
                    }
                    rows.append(row)
                except (ValueError, IndexError) as e:
                    print(f"Skipping malformed row: {e}")
                    continue
        
        if not rows:
            print("Warning: No data rows found in SCFI table")
            return pd.DataFrame()
        
        df = pd.DataFrame(rows)
        df['date'] = datetime.now().strftime('%Y-%m-%d')
        
        # Clean change percentage
        if 'week_over_week_change' in df.columns:
            df['week_over_week_change'] = (
                df['week_over_week_change']
                .str.replace('%', '')
                .str.replace('+', '')
                .apply(lambda x: float(x) if x else None)
            )
        
        print(f"Successfully scraped {len(df)} SCFI routes")
        return df
        
    except requests.exceptions.Timeout:
        print("Warning: SCFI scraper timeout (website unreachable). Continuing...")
        return pd.DataFrame()
    except requests.exceptions.ConnectionError:
        print("Warning: SCFI scraper connection error. Continuing...")
        return pd.DataFrame()
    except Exception as e:
        print(f"Warning: SCFI scraper failed: {e}")
        print("This is expected if the website structure changed.")
        print("Continuing with other data sources...")
        return pd.DataFrame()


def parse_manual_excel(excel_path: str) -> pd.DataFrame:
    """
    Parse manually downloaded SCFI Excel file (backup if scraping fails)
    
    Args:
        excel_path: Path to manually downloaded SCFI Excel
    """
    try:
        import openpyxl
    except ImportError:
        print("Warning: openpyxl not installed. Cannot parse Excel. Install with: pip install openpyxl")
        return pd.DataFrame()
    
    try:
        df = pd.read_excel(excel_path, sheet_name=0)
        
        # Clean column names
        df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_')
        
        # Parse date column
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
        elif 'week' in df.columns:
            df['date'] = pd.to_datetime(df['week'])
        
        print(f"Parsed {len(df)} records from Excel")
        return df
        
    except Exception as e:
        print(f"Warning: Failed to parse Excel: {e}")
        return pd.DataFrame()


def normalize_and_save(df: pd.DataFrame) -> None:
    """Normalize SCFI data and save to SQLite"""
    if df.empty:
        print("No SCFI data to save")
        return
    
    df_normalized = pd.DataFrame({
        'id': df['route'].astype(str) + '_' + df['date'].astype(str),
        'date': pd.to_datetime(df['date']),
        'route': df['route'],
        'rate_usd_per_teu': df['current_rate'].astype(int),
        'week_over_week_change': df.get('week_over_week_change', None),
        'timestamp': datetime.now()
    })
    
    # Drop duplicates
    df_normalized = df_normalized.drop_duplicates(subset=['id'])
    
    try:
        engine = create_engine(DB_URL)
        df_normalized.to_sql(
            'scfi_freight_rates',
            engine,
            if_exists='append',
            index=False,
            method='multi'
        )
        print(f"Saved {len(df_normalized)} SCFI freight records to database")
    except Exception as e:
        print(f"Error saving SCFI data to database: {e}")


if __name__ == "__main__":
    print(f"[{METIS_MODE}] SCFI Freight Rates")

    print("Fetching Shanghai Containerized Freight Index (SCFI)...")

    # Try scraping
    df = scrape_current_scfi()

    # Fallback: check for manual Excel download
    if df.empty:
        from pathlib import Path
        excel_path = Path("data/downloads/scfi.xlsx")
        if excel_path.exists():
            print(f"Scraping failed. Trying manual Excel: {excel_path}")
            df = parse_manual_excel(str(excel_path))

    # Save if we got data
    if not df.empty:
        normalize_and_save(df)
    else:
        print("No SCFI data available. This is okay - freight rates are secondary data source.")
