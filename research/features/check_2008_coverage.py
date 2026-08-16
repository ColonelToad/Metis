"""
Coverage check for the 2008 GFC pilot: which sources have real data back to
2005-2007, the window where OMD found measurable precursors?

Run from C:\\Users\\legot\\Metis:
    python research/features/check_2008_coverage.py
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
engine = create_engine(DB_URL)

SOURCES = {
    "ng_futures_daily": "SELECT MIN(date), MAX(date), COUNT(*) FROM ng_futures_daily",
    "eia_storage": "SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM eia_storage",
    "eia_production": "SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM eia_production",
    "stock_prices (EQT)": "SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM stock_prices WHERE ticker='EQT'",
    "stock_prices (XLE)": "SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM stock_prices WHERE ticker='XLE'",
    "bls_ppi": "SELECT MIN(date), MAX(date), COUNT(*) FROM bls_ppi",
    "fred_macro (wti)": "SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM fred_macro WHERE series_id='DCOILWTICO'",
    "lobbying_filings": "SELECT MIN(dt_posted), MAX(dt_posted), COUNT(*) FROM lobbying_filings",
    "lobbying_filings (ENG)": """
        SELECT MIN(lf.dt_posted), MAX(lf.dt_posted), COUNT(*)
        FROM lobbying_filings lf
        JOIN lobbying_activities la ON lf.filing_uuid = la.filing_uuid
        WHERE la.general_issue_code IN ('ENG','FUE')
    """,
    "storm_events": "SELECT MIN(begin_date), MAX(begin_date), COUNT(*) FROM storm_events",
}

with engine.connect() as conn:
    print(f"{'Source':<35} {'Min date':<15} {'Max date':<15} {'N rows':>8}")
    print("-" * 80)
    for name, q in SOURCES.items():
        try:
            row = conn.execute(text(q)).fetchone()
            min_d = str(row[0])[:10] if row[0] else "NULL"
            max_d = str(row[1])[:10] if row[1] else "NULL"
            n = row[2] or 0
            print(f"{name:<35} {min_d:<15} {max_d:<15} {n:>8,}")
        except Exception as e:
            print(f"{name:<35} ERROR: {e}")
