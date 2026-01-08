import sqlite3

conn = sqlite3.connect('data/metis.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('Tables in SQLite DB:', [t[0] for t in cursor.fetchall()])

for table in ['eia_storage', 'fred_macro', 'stock_prices', 'tomtom_traffic']:
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f'{table}: {count} records')
    except:
        print(f'{table}: not found')
conn.close()
