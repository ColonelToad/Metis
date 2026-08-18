import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
engine = create_engine(DB_URL)

fix_query = """
    UPDATE stock_prices
    SET timestamp = date(CAST(timestamp AS INTEGER), 'unixepoch')
    WHERE timestamp NOT LIKE '%-%';
"""

with engine.begin() as conn:
    result = conn.execute(text(fix_query))
    print(f"Rows updated: {result.rowcount}")
    if result.rowcount > 0:
        print("Timestamps successfully normalized!")
    else:
        print("No rows matched the condition. We might need to look closer at the data type.")