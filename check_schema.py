import lancedb

# Based on your script, the database is located here relative to the root
db_path = "research/data/dev/lance" 

try:
    db = lancedb.connect(db_path)
    table = db.open_table("metis_documents")
    print("\n--- LanceDB Schema for 'metis_documents' ---")
    print(table.schema)
    print("--------------------------------------------\n")
except Exception as e:
    print(f"Error accessing database: {e}")