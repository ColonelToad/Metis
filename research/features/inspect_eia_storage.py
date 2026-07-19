"""
Run from C:\\Users\\legot\\Metis:
    python research/features/inspect_eia_storage.py
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
engine = create_engine(DB_URL)

with engine.connect() as conn:
    print("=== schema ===")
    for row in conn.execute(text("PRAGMA table_info(eia_storage)")).fetchall():
        print(" ", row)

    print("\n=== all columns, all 8 rows for 2025-12-05 ===")
    for row in conn.execute(text("SELECT * FROM eia_storage WHERE date(timestamp) = '2025-12-05'")).fetchall():
        print(" ", row)

    print("\n=== distinct non-timestamp column values across full table (sample) ===")
    cols = [r[1] for r in conn.execute(text("PRAGMA table_info(eia_storage)")).fetchall() if r[1] != 'timestamp' and r[1] != 'storage_bcf']
    for c in cols:
        vals = conn.execute(text(f'SELECT DISTINCT "{c}" FROM eia_storage LIMIT 20')).fetchall()
        print(f"  {c}: {[v[0] for v in vals]}")
