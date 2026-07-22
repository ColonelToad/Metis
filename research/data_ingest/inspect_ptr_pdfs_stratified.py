"""
Run from C:\\Users\\legot\\Metis (pdfplumber must already be installed):
    python research/data_ingest/inspect_ptr_pdfs_stratified.py

Pulls real sample DocIDs directly from house_ptr_index (2 short-format,
1 long-format per year as a control) and tests actual PDF extraction against
each -- purpose is to properly test whether DocID length predicts empty/
scanned PDFs across years, rather than generalizing from a single example.
"""
import os
import requests
import pdfplumber
from io import BytesIO
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
engine = create_engine(DB_URL)

BASE_URL = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs"

samples = []
with engine.connect() as conn:
    for year in [2015, 2018, 2021, 2024, 2026]:
        short = conn.execute(text(
            "SELECT DocID FROM house_ptr_index WHERE Year=:y AND LENGTH(DocID)=7 LIMIT 2"
        ), {"y": str(year)}).fetchall()
        long_ = conn.execute(text(
            "SELECT DocID FROM house_ptr_index WHERE Year=:y AND LENGTH(DocID)=8 LIMIT 1"
        ), {"y": str(year)}).fetchall()
        for (docid,) in short:
            samples.append((year, "short(7)", docid))
        for (docid,) in long_:
            samples.append((year, "long(8) control", docid))

print(f"Testing {len(samples)} samples across years 2015-2026\n")

results = []
for year, kind, docid in samples:
    url = f"{BASE_URL}/{year}/{docid}.pdf"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        with pdfplumber.open(BytesIO(resp.content)) as pdf:
            text_out = "".join((p.extract_text() or "") for p in pdf.pages)
            n_chars = len(text_out.strip())
            status = "HAS_TEXT" if n_chars > 20 else "EMPTY"
    except Exception as e:
        status = f"ERROR: {e}"
        n_chars = 0

    results.append((year, kind, docid, status, n_chars))
    print(f"  {year} {kind:16s} {docid:10s} -> {status} ({n_chars} chars)")

print("\n=== Summary ===")
short_results = [r for r in results if r[1].startswith("short")]
long_results = [r for r in results if r[1].startswith("long")]
short_empty = sum(1 for r in short_results if r[3] == "EMPTY")
long_empty = sum(1 for r in long_results if r[3] == "EMPTY")
print(f"Short(7) DocIDs: {short_empty}/{len(short_results)} empty")
print(f"Long(8) DocIDs:  {long_empty}/{len(long_results)} empty")
