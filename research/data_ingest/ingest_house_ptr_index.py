"""
House Clerk Financial Disclosure Index Fetcher (Stage 1 of 2)

Fetches the House Clerk's annual financial disclosure index and filters to
Periodic Transaction Reports (PTRs, FilingType='P') -- these are the actual
STOCK Act trade disclosures. This stage only produces the filing index
(who filed, when, and the PDF URL); it does not parse trade-level detail out
of the PDFs themselves -- that's stage 2 (ingest_congress_trades_pdf_parse.py,
not yet built), since PDF table extraction needs to be tested against real
filings before trusting it at scale, not written blind.

Pipeline (confirmed against a real extracted PTR PDF, not just documentation):
    https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{YEAR}FD.zip
    -> contains {YEAR}FD.xml, one row per disclosure filed that year
    -> filter FilingType == 'P' for PTRs specifically
    -> PDF at https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{YEAR}/{DocID}.pdf

XML tag names below are best-effort from public documentation, NOT independently
confirmed against a live file. This fetch prints the actual root tag and first
row's element names before parsing, so a wrong assumption surfaces immediately
as a clear diagnostic instead of a silent empty/wrong result.
"""
import os
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from datetime import datetime
import pandas as pd
import requests
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
from sqlalchemy import create_engine

sys.path.append(str(Path(__file__).resolve().parents[2]))
from research.common import runtime_config as rc

load_dotenv()
DB_URL = rc.get_db_url()

BASE_URL = "https://disclosures-clerk.house.gov/public_disc"


def fetch_year_index(year: int) -> pd.DataFrame:
    """Fetch and parse one year's disclosure index, filtered to PTRs only."""
    url = f"{BASE_URL}/financial-pdfs/{year}FD.zip"
    print(f"Fetching House disclosure index: {url}")

    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Error fetching {year}FD.zip: {e}")
        return pd.DataFrame()

    try:
        with zipfile.ZipFile(BytesIO(resp.content)) as zf:
            xml_name = f"{year}FD.xml"
            if xml_name not in zf.namelist():
                print(f"  Expected {xml_name} not found in zip. Contents: {zf.namelist()}")
                return pd.DataFrame()
            xml_bytes = zf.read(xml_name)
    except zipfile.BadZipFile as e:
        print(f"  Bad zip file for {year}: {e}")
        return pd.DataFrame()

    root = ET.fromstring(xml_bytes)
    print(f"  XML root tag: '{root.tag}', {len(root)} child elements")

    records = []
    for i, member in enumerate(root):
        row = {child.tag: (child.text or '').strip() for child in member}
        if i == 0:
            print(f"  First row element names: {list(row.keys())}")
        records.append(row)

    if not records:
        print(f"  No records found for {year}")
        return pd.DataFrame()

    df = pd.DataFrame(records)

    # Field names below are the commonly-documented House Clerk XML schema --
    # verify against the printed keys above on first real run.
    filing_type_col = next((c for c in df.columns if c.lower() in ('filingtype',)), None)
    if filing_type_col is None:
        print(f"  Could not find a FilingType-like column. Available columns: {list(df.columns)}")
        return df  # return unfiltered so it's still inspectable

    n_before = len(df)
    df = df[df[filing_type_col] == 'P'].copy()
    print(f"  {year}: {n_before} total filings -> {len(df)} PTRs (FilingType='P')")

    doc_id_col = next((c for c in df.columns if c.lower() in ('docid', 'doc_id')), None)
    if doc_id_col:
        df['pdf_url'] = df[doc_id_col].apply(
            lambda docid: f"{BASE_URL}/ptr-pdfs/{year}/{docid}.pdf" if docid else None)
    else:
        print(f"  Could not find a DocID-like column to construct PDF URLs. "
              f"Available columns: {list(df.columns)}")

    df['filing_year'] = year
    return df


def fetch_range(start_year: int, end_year: int) -> pd.DataFrame:
    frames = []
    for year in range(start_year, end_year + 1):
        df = fetch_year_index(year)
        if not df.empty:
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def save_to_db(df: pd.DataFrame) -> int:
    if df.empty:
        print("No PTR filing index records to save")
        return 0
    engine = create_engine(DB_URL)
    df.to_sql('house_ptr_index', engine, if_exists='replace', index=False)
    print(f"Saved {len(df)} PTR filing index records to 'house_ptr_index' "
          f"(filing metadata + PDF URLs only -- trade-level detail requires stage 2)")
    return len(df)


def main():
    rc.log_mode("House PTR Index")
    if not rc.require_real_mode("House Clerk PTR index"):
        return 0

    start_year = int(os.getenv("PTR_INDEX_START_YEAR", "2015"))
    end_year = datetime.now().year
    print(f"Fetching House PTR filing index ({start_year}-{end_year})...")

    df = fetch_range(start_year, end_year)
    return save_to_db(df)


if __name__ == "__main__":
    main()
