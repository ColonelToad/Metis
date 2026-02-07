#!/usr/bin/env python3
"""Diagnose missing data sources in database"""
import sqlite3
import pandas as pd

conn = sqlite3.connect('data/metis.db')

# Check what tables exist
tables = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name", conn)
print('Tables in database:')
print(tables.to_string(index=False))

# Check record counts
print('\n\nRecord counts and date ranges:')
important_tables = ['ng_futures_daily', 'eia_storage', 'eia_production', 'fred_macro', 'traffic_flow', 'tomtom_traffic', 'congress_bills']
for table in important_tables:
    try:
        count = pd.read_sql_query(f'SELECT COUNT(*) as cnt FROM {table}', conn).iloc[0, 0]
        date_range = pd.read_sql_query(f'SELECT MIN(date) as min_date, MAX(date) as max_date FROM {table}', conn)
        min_date = date_range.iloc[0, 0]
        max_date = date_range.iloc[0, 1]
        print(f'{table:30s}: {count:7d} records,  {min_date} to {max_date}')
    except Exception as e:
        print(f'{table:30s}: ERROR - {str(e)[:50]}')

# Check FRED data specifically
print('\n\nFRED macro columns and sample:')
try:
    fred_sample = pd.read_sql_query("SELECT * FROM fred_macro LIMIT 5", conn)
    print(f"FRED columns: {list(fred_sample.columns)}")
    print(f"FRED shape: {fred_sample.shape}")
    print(f"\nFRED sample:")
    print(fred_sample)
except Exception as e:
    print(f"ERROR reading FRED: {e}")

# Check if traffic data exists
print('\n\nTraffic data check:')
try:
    traffic = pd.read_sql_query("SELECT * FROM tomtom_traffic LIMIT 5", conn)
    print(f"Traffic columns: {list(traffic.columns)}")
    print(f"Traffic records: {pd.read_sql_query('SELECT COUNT(*) FROM tomtom_traffic', conn).iloc[0,0]}")
except Exception as e:
    print(f"Traffic table error: {e}")

conn.close()
