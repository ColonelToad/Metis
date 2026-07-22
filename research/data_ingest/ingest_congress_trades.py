"""
Congressional Stock Trading Disclosures Ingestion (STOCK Act)

The previous version of this script targeted congress.gov/api/v1/stock-trades,
which does not exist -- the real Congress.gov API only covers legislative data
(bills, members, committees), never financial disclosures. STOCK Act trade
disclosures are filed as PDFs with the House Clerk and Senate eFD systems and
have no official structured API.

This version uses House Stock Watcher and Senate Stock Watcher -- community
projects that transcribe those official filings into structured JSON, served
as flat static files (not a queried API, so no rate limits/auth to worry
about). Worth being explicit about the tradeoff: these are volunteer-run and
NOT authoritative government sources. Treat any single trade as "worth
checking ptr_link" rather than ground truth -- same posture as the news-
mention signal elsewhere in this pipeline.

House: https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json
    Flat list, confirmed fields: disclosure_year, disclosure_date, transaction_date,
    owner, ticker, asset_description, type, amount, representative, district,
    state, ptr_link, cap_gains_over_200_usd, industry, sector, party

Senate: https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json
    URL inferred from the House naming convention and the senate-stock-watcher-data
    repo's documented 'aggregate/' folder (same author, same project pattern) --
    NOT independently confirmed byte-for-byte. This fetch is written defensively:
    it prints the actual top-level keys of whatever it receives before parsing,
    so a wrong URL or differently-named field surfaces immediately as a clear
    diagnostic rather than a silent empty result.
"""
import os
import re
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.append(str(Path(__file__).resolve().parents[2]))
from research.common import runtime_config as rc

load_dotenv()
DB_URL = rc.get_db_url()

HOUSE_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"
SENATE_URL = "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json"

# Curated energy-adjacent tickers, used as a fallback for Senate rows (which
# have no native sector/industry field) and as a sanity cross-check for House
# rows already flagged sector=='Energy'. NOT exhaustive -- majors, E&P, and
# midstream names most relevant to NG specifically, not a broad energy-ETF
# list like the previous version used (which only matched ETFs, never an
# actual company ticker like XOM or CVX).
ENERGY_TICKERS = {
    'XOM', 'CVX', 'COP', 'EOG', 'PXD', 'OXY', 'MRO', 'DVN', 'FANG', 'HES',
    'SLB', 'HAL', 'BKR', 'KMI', 'WMB', 'OKE', 'ET', 'EPD', 'ENB', 'TRP',
    'LNG', 'CQP', 'NEE', 'DUK', 'SO', 'D', 'AEP', 'EXC', 'SRE', 'PCG',
    'BP', 'SHEL', 'TTE', 'EQNR',
}


def parse_amount_range(amount_str):
    """
    Parse '$1,001 - $15,000' or 'Over $50,000,000' into (low, high) floats.
    Returns (None, None) if unparseable.
    """
    if not amount_str or pd.isna(amount_str):
        return None, None
    nums = re.findall(r'[\d,]+(?:\.\d+)?', str(amount_str))
    nums = [float(n.replace(',', '')) for n in nums]
    if len(nums) == 2:
        return nums[0], nums[1]
    elif len(nums) == 1:
        # "Over $X" style brackets
        return nums[0], None
    return None, None


def is_energy(ticker, sector=None, industry=None) -> bool:
    if sector and str(sector).strip().lower() == 'energy':
        return True
    if industry and 'oil' in str(industry).lower():
        return True
    if ticker and str(ticker).strip().upper() in ENERGY_TICKERS:
        return True
    return False


def fetch_house_trades() -> pd.DataFrame:
    print("Fetching House trades (House Stock Watcher)...")
    resp = requests.get(HOUSE_URL, timeout=60)
    resp.raise_for_status()
    raw = resp.json()
    print(f"  Received {len(raw)} raw House transaction records")
    if raw:
        print(f"  Sample record keys: {list(raw[0].keys())}")

    df = pd.DataFrame(raw)
    if df.empty:
        return df

    out = pd.DataFrame({
        'chamber': 'house',
        'member_name': df.get('representative', ''),
        'state': df.get('state', ''),
        'district': df.get('district', None),
        'party': df.get('party', None),
        'transaction_date': pd.to_datetime(df.get('transaction_date'), errors='coerce'),
        'disclosure_date': pd.to_datetime(df.get('disclosure_date'), errors='coerce'),
        'owner': df.get('owner', ''),
        'ticker': df.get('ticker', '').replace('--', None),
        'asset_description': df.get('asset_description', ''),
        'asset_type': None,
        'transaction_type': df.get('type', ''),
        'amount_range': df.get('amount', ''),
        'industry': df.get('industry', None),
        'sector': df.get('sector', None),
        'ptr_link': df.get('ptr_link', None),
    })
    out['amount_low'], out['amount_high'] = zip(*out['amount_range'].apply(parse_amount_range))
    out['is_energy_related'] = out.apply(
        lambda r: is_energy(r['ticker'], r['sector'], r['industry']), axis=1)
    return out


def fetch_senate_trades() -> pd.DataFrame:
    print("Fetching Senate trades (Senate Stock Watcher)...")
    try:
        resp = requests.get(SENATE_URL, timeout=60)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ERROR fetching Senate data from {SENATE_URL}: {e}")
        print("  This URL was inferred from the House naming convention, not independently "
              "confirmed. If this fails, check https://github.com/timothycarambat/"
              "senate-stock-watcher-data for the current aggregate file path.")
        return pd.DataFrame()

    raw = resp.json()
    print(f"  Received Senate data: top-level type={type(raw).__name__}, "
          f"length={len(raw) if hasattr(raw, '__len__') else 'n/a'}")
    if isinstance(raw, list) and raw:
        print(f"  Sample record keys: {list(raw[0].keys())}")
    elif isinstance(raw, dict):
        print(f"  Top-level keys: {list(raw.keys())}")
        print("  Expected a flat list based on the 'aggregate/' folder description -- "
              "got a dict instead. Parsing logic below may need adjusting once this "
              "structure is visible; stopping here rather than guessing further.")
        return pd.DataFrame()

    df = pd.DataFrame(raw)
    if df.empty:
        return df

    # Field names are inferred from the per-senator nested format documented in the
    # repo README (transaction_date, owner, ticker, asset_description, asset_type,
    # type, amount) plus the outer per-filer fields (first_name, last_name, office,
    # ptr_link) -- the aggregate/ format may flatten these under slightly different
    # keys. Adjust the .get() calls below once the printed sample keys above confirm
    # the real shape.
    name_col = 'senator' if 'senator' in df.columns else None
    if name_col is None and 'first_name' in df.columns and 'last_name' in df.columns:
        member_name = df['first_name'].astype(str) + ' ' + df['last_name'].astype(str)
    else:
        member_name = df.get(name_col, df.get('office', ''))

    out = pd.DataFrame({
        'chamber': 'senate',
        'member_name': member_name,
        'state': df.get('state', None),
        'district': None,
        'party': None,  # not provided by this source
        'transaction_date': pd.to_datetime(df.get('transaction_date'), errors='coerce'),
        'disclosure_date': pd.to_datetime(df.get('date_recieved', df.get('disclosure_date')), errors='coerce'),
        'owner': df.get('owner', ''),
        'ticker': df.get('ticker', pd.Series(dtype=object)).replace('--', None),
        'asset_description': df.get('asset_description', ''),
        'asset_type': df.get('asset_type', None),
        'transaction_type': df.get('type', ''),
        'amount_range': df.get('amount', ''),
        'industry': None,  # not provided by this source
        'sector': None,
        'ptr_link': df.get('ptr_link', None),
    })
    out['amount_low'], out['amount_high'] = zip(*out['amount_range'].apply(parse_amount_range))
    out['is_energy_related'] = out.apply(
        lambda r: is_energy(r['ticker'], r['sector'], r['industry']), axis=1)
    return out


def save_to_db(df: pd.DataFrame) -> int:
    if df.empty:
        print("No congressional trades to save")
        return 0
    engine = create_engine(DB_URL)
    df.to_sql('congress_trades', engine, if_exists='replace', index=False)
    print(f"Saved {len(df)} congressional trade records to database")
    return len(df)


def main():
    rc.log_mode("Congress Trades")
    if not rc.require_real_mode("Congressional trades (House/Senate Stock Watcher)"):
        return 0

    house_df = fetch_house_trades()
    senate_df = fetch_senate_trades()

    frames = [d for d in (house_df, senate_df) if not d.empty]
    if not frames:
        print("No congressional trades fetched from either chamber")
        return 0

    combined = pd.concat(frames, ignore_index=True)
    print(f"\nTotal: {len(combined)} trades ({len(house_df)} House, {len(senate_df)} Senate)")
    print(f"Energy-related: {combined['is_energy_related'].sum()} "
          f"({combined['is_energy_related'].mean()*100:.1f}%)")

    return save_to_db(combined)


if __name__ == "__main__":
    main()
