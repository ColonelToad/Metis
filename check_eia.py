import sqlite3

conn = sqlite3.connect('data/metis.db')
cursor = conn.cursor()

cursor.execute('SELECT * FROM eia_storage LIMIT 5')
print('Columns:', [desc[0] for desc in cursor.description])
for row in cursor:
    print(row)
    print('Types:', [type(val).__name__ for val in row])
    break

conn.close()
