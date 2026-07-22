"""
Run from C:\\Users\\legot\\Metis (after `pip install pdfplumber`):
    python research/data_ingest/inspect_ptr_pdfs.py

Downloads a small, deliberately varied sample of real PTR PDFs and prints
their raw extracted text -- purpose is to see actual whitespace/layout
structure before writing any parsing regex, not to parse anything yet.
"""
import requests
import pdfplumber
from io import BytesIO

SAMPLES = {
    "Ashford_2015_single (from your own data)":
        "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2015/20002776.pdf",
    "Babin_2015_short_docid (tests the odd 7-digit ID format)":
        "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2015/9106294.pdf",
    "Barletta_2015":
        "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2015/20002550.pdf",
}

for label, url in SAMPLES.items():
    print(f"\n{'='*70}\n{label}\n{url}\n{'='*70}")
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        with pdfplumber.open(BytesIO(resp.content)) as pdf:
            print(f"  {len(pdf.pages)} page(s)")
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                print(f"  --- page {i+1} raw text ---")
                print(text)
                tables = page.extract_tables()
                print(f"  --- page {i+1} extract_tables() found {len(tables)} table(s) ---")
                for t in tables:
                    for row in t:
                        print(f"    {row}")
    except Exception as e:
        print(f"  ERROR: {e}")
