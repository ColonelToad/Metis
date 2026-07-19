"""
Run from C:\\Users\\legot\\Metis:
    python research/features/check_single_date_dup.py
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
engine = create_engine(DB_URL)

CHECK_DATE = "2026-04-01"

queries = {
    "fred_macro": f"SELECT * FROM fred_macro WHERE date(timestamp) = '{CHECK_DATE}'",
    "census_permits": f"SELECT * FROM census_permits WHERE date(date) = '{CHECK_DATE}'",
    "congress_bills": f"SELECT * FROM congress_bills WHERE date(timestamp) = '{CHECK_DATE}'",
    "eia_storage": f"SELECT * FROM eia_storage WHERE date(timestamp) = '{CHECK_DATE}'",
    "eia_production": f"SELECT * FROM eia_production WHERE date(timestamp) = '{CHECK_DATE}'",
    "cme_futures_daily (natural_gas)": f"SELECT * FROM cme_futures_daily WHERE contract_type='natural_gas' AND date(date) = '{CHECK_DATE}'",
    "ng_futures_daily": f"SELECT * FROM ng_futures_daily WHERE date(date) = '{CHECK_DATE}'",
    "bls_ppi": f"SELECT * FROM bls_ppi WHERE date(date) = '{CHECK_DATE}'",
}

with engine.connect() as conn:
    for name, q in queries.items():
        try:
            result = conn.execute(text(q)).fetchall()
            print(f"\n=== {name} ===  ({len(result)} rows)")
            for row in result[:10]:
                print(f"  {row}")
        except Exception as e:
            print(f"\n=== {name} ===  ERROR: {e}")
