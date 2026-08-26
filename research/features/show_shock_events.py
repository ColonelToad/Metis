"""
Run from C:\\Users\\legot\\Metis:
    python research/features/show_shock_events.py
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
engine = create_engine(DB_URL)

with engine.connect() as conn:
    print("=== shock_events catalog ===")
    for row in conn.execute(
        text("SELECT id, name, start, end, type, severity, region FROM shock_events ORDER BY start")
    ).fetchall():
        print(f"\n[{row[0]}] {row[1]}")
        print(f"     {row[2]} -> {row[3]}  |  type={row[4]}  severity={row[5]}  region={row[6]}")
