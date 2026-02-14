#!/usr/bin/env python3
"""
Clean synthetic data from database.
Removes bls_ppi and census_permits tables which only contain synthetic data.
"""
import sqlite3
from pathlib import Path

db_path = Path(__file__).parent / "data" / "metis.db"

if not db_path.exists():
    print(f"Database not found: {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

tables_to_drop = ['bls_ppi', 'census_permits']

for table in tables_to_drop:
    try:
        cursor.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
        print(f"✓ Dropped table: {table}")
    except Exception as e:
        print(f"✗ Failed to drop {table}: {e}")

conn.close()
print("\n✓ Database cleaned: synthetic data removed")
print("  Tables will be recreated with real data when REAL mode is used")
