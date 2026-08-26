"""
Run from C:\\Users\\legot\\Metis:
    python research/features/update_shock_catalog.py
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
engine = create_engine(DB_URL)

with engine.connect() as conn:
    print("=== shock_events schema ===")
    for row in conn.execute(text("PRAGMA table_info(shock_events)")).fetchall():
        print(" ", row)

    print("\n=== shock_regimes schema ===")
    for row in conn.execute(text("PRAGMA table_info(shock_regimes)")).fetchall():
        print(" ", row)
