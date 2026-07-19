"""
Diagnose the 256x row-duplication in the OOS feature build.
Checks every source table engineer_features.py merges on 'date', for a single
known-duplicated date (2025-12-05), to find which one(s) have duplicate rows.

Run from C:\\Users\\legot\\Metis:
    python research/features/diagnose_duplication.py
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
engine = create_engine(DB_URL)

CHECK_DATE = "2025-12-05"

queries = {
    "eia_storage": f"SELECT * FROM eia_storage WHERE date(timestamp) = '{CHECK_DATE}'",
    "eia_production": f"SELECT * FROM eia_production WHERE date(timestamp) = '{CHECK_DATE}'",
    "fred_macro": f"SELECT * FROM fred_macro WHERE date(timestamp) = '{CHECK_DATE}'",
    "census_permits": f"SELECT * FROM census_permits WHERE date(date) = '{CHECK_DATE}'",
    "congress_bills": f"SELECT * FROM congress_bills WHERE date(timestamp) = '{CHECK_DATE}'",
    "cme_futures_daily (all contracts)": f"SELECT contract_type, COUNT(*) as n FROM cme_futures_daily WHERE date(date) = '{CHECK_DATE}' GROUP BY contract_type",
    "grid_lmp_multi_iso (all ISOs)": f"SELECT iso, COUNT(*) as n FROM grid_lmp_multi_iso WHERE date(timestamp) = '{CHECK_DATE}' GROUP BY iso",
    "bls_ppi (all series)": f"SELECT series_id, COUNT(*) as n FROM bls_ppi WHERE date(date) = '{CHECK_DATE}' GROUP BY series_id",
}

with engine.connect() as conn:
    for name, q in queries.items():
        try:
            result = conn.execute(text(q)).fetchall()
            print(f"\n=== {name} ===")
            print(f"  {len(result)} row(s) returned for {CHECK_DATE}")
            for row in result[:10]:
                print(f"  {row}")
        except Exception as e:
            print(f"\n=== {name} ===")
            print(f"  ERROR: {e}")
