"""
Run from C:\\Users\\legot\\Metis:
    python research/features/verify_eia_storage_fix.py
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
engine = create_engine(DB_URL)

with engine.connect() as conn:
    print("=== row count ===")
    print(conn.execute(text("SELECT COUNT(*) FROM eia_storage")).fetchone())

    print("\n=== distinct area-name values ===")
    print(conn.execute(text('SELECT DISTINCT "area-name" FROM eia_storage')).fetchall())

    print("\n=== date range ===")
    print(conn.execute(text("SELECT MIN(timestamp), MAX(timestamp) FROM eia_storage")).fetchone())

    print("\n=== the specific date we checked before ===")
    print(conn.execute(text("SELECT * FROM eia_storage WHERE date(timestamp) = '2025-12-05'")).fetchall())

    print("\n=== any remaining duplicate dates? ===")
    dupes = conn.execute(text(
        "SELECT date(timestamp), COUNT(*) as n FROM eia_storage GROUP BY date(timestamp) HAVING n > 1"
    )).fetchall()
    print(f"{len(dupes)} duplicated dates" + (f": {dupes[:5]}" if dupes else ""))
