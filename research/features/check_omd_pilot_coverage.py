"""
Coverage check for the 2008 GFC OMD pilot after backfills.
Confirms which sources now cover the 2005-2007 precursor window.

Run from C:\\Users\\legot\\Metis:
    python research/features/check_omd_pilot_coverage.py
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
engine = create_engine(DB_URL)

PILOT_START = "2005-01-01"
PILOT_END = "2009-12-31"

SOURCES = {
    "ng_futures_daily (price spine)": f"""
        SELECT MIN(date), MAX(date),
               COUNT(*) as total,
               SUM(CASE WHEN date >= '{PILOT_START}' AND date <= '{PILOT_END}' THEN 1 ELSE 0 END) as in_window
        FROM ng_futures_daily""",
    "eia_storage": f"""
        SELECT MIN(timestamp), MAX(timestamp),
               COUNT(*) as total,
               SUM(CASE WHEN timestamp >= '{PILOT_START}' AND timestamp <= '{PILOT_END}' THEN 1 ELSE 0 END) as in_window
        FROM eia_storage""",
    "eia_production": f"""
        SELECT MIN(timestamp), MAX(timestamp),
               COUNT(*) as total,
               SUM(CASE WHEN timestamp >= '{PILOT_START}' AND timestamp <= '{PILOT_END}' THEN 1 ELSE 0 END) as in_window
        FROM eia_production""",
    "fred_macro (wti_crude_price)": f"""
        SELECT MIN(timestamp), MAX(timestamp),
               COUNT(*) as total,
               SUM(CASE WHEN timestamp >= '{PILOT_START}' AND timestamp <= '{PILOT_END}' THEN 1 ELSE 0 END) as in_window
        FROM fred_macro WHERE wti_crude_price IS NOT NULL""",
    "stock_prices (XLE)": f"""
        SELECT MIN(timestamp), MAX(timestamp),
               COUNT(*) as total,
               SUM(CASE WHEN timestamp >= '{PILOT_START}' AND timestamp <= '{PILOT_END}' THEN 1 ELSE 0 END) as in_window
        FROM stock_prices WHERE ticker='XLE'""",
    "stock_prices (EQT)": f"""
        SELECT MIN(timestamp), MAX(timestamp),
               COUNT(*) as total,
               SUM(CASE WHEN timestamp >= '{PILOT_START}' AND timestamp <= '{PILOT_END}' THEN 1 ELSE 0 END) as in_window
        FROM stock_prices WHERE ticker='EQT'""",
    "lobbying_filings (ENG/FUE)": f"""
        SELECT MIN(lf.dt_posted), MAX(lf.dt_posted),
               COUNT(*) as total,
               SUM(CASE WHEN lf.dt_posted >= '{PILOT_START}' AND lf.dt_posted <= '{PILOT_END}' THEN 1 ELSE 0 END) as in_window
        FROM lobbying_filings lf
        JOIN lobbying_activities la ON lf.filing_uuid = la.filing_uuid
        WHERE la.general_issue_code IN ('ENG','FUE')""",
    "congress_bills (energy-related)": f"""
        SELECT MIN(latest_action_date), MAX(latest_action_date),
               COUNT(*) as total,
               SUM(CASE WHEN latest_action_date >= '{PILOT_START}' AND latest_action_date <= '{PILOT_END}' THEN 1 ELSE 0 END) as in_window
        FROM congress_bills WHERE is_energy_related=1""",
}

with engine.connect() as conn:
    print(f"2008 GFC OMD Pilot -- coverage check for window {PILOT_START} to {PILOT_END}\n")
    print(f"{'Source':<40} {'Min date':<12} {'Max date':<12} {'Total':>8} {'In window':>10}")
    print("-" * 88)
    for name, q in SOURCES.items():
        try:
            row = conn.execute(text(q)).fetchone()
            min_d = str(row[0])[:10] if row[0] else "NULL"
            max_d = str(row[1])[:10] if row[1] else "NULL"
            total = row[2] or 0
            in_window = row[3] or 0
            flag = "✓" if in_window > 0 else "✗"
            print(f"{flag} {name:<38} {min_d:<12} {max_d:<12} {total:>8,} {in_window:>10,}")
        except Exception as e:
            print(f"✗ {name:<38} ERROR: {e}")
