"""
Run from C:\\Users\\legot\\Metis:
    python research/features/check_docid_formats.py
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
engine = create_engine(DB_URL)

with engine.connect() as conn:
    print("=== DocID length distribution by year ===")
    rows = conn.execute(text(
        "SELECT Year, LENGTH(DocID) as docid_len, COUNT(*) as n "
        "FROM house_ptr_index GROUP BY Year, docid_len ORDER BY Year, docid_len"
    )).fetchall()
    for year, length, n in rows:
        print(f"  {year}: length={length} -> {n} filings")

    print("\n=== overall split ===")
    rows = conn.execute(text(
        "SELECT LENGTH(DocID) as docid_len, COUNT(*) as n "
        "FROM house_ptr_index GROUP BY docid_len ORDER BY docid_len"
    )).fetchall()
    total = sum(n for _, n in rows)
    for length, n in rows:
        print(f"  length={length}: {n} filings ({n/total*100:.1f}%)")
