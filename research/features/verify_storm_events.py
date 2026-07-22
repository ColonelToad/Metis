"""
Run from C:\\Users\\legot\\Metis:
    python research/features/verify_storm_events.py
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
engine = create_engine(DB_URL)

with engine.connect() as conn:
    print("=== total row count ===")
    print(conn.execute(text("SELECT COUNT(*) FROM storm_events")).fetchone())

    print("\n=== rows per year ===")
    rows = conn.execute(text(
        "SELECT strftime('%Y', begin_date) as yr, COUNT(*) as n "
        "FROM storm_events GROUP BY yr ORDER BY yr"
    )).fetchall()
    for yr, n in rows:
        print(f"  {yr}: {n}")

    print("\n=== date range ===")
    print(conn.execute(text("SELECT MIN(begin_date), MAX(begin_date) FROM storm_events")).fetchone())

    print("\n=== any duplicate event_ids? ===")
    dupes = conn.execute(text(
        "SELECT event_id, COUNT(*) as n FROM storm_events GROUP BY event_id HAVING n > 1"
    )).fetchall()
    print(f"{len(dupes)} duplicated event_ids")
