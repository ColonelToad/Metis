import lancedb

# Use the exact absolute path that Rust is resolving to
uri = r"C:\Users\legot\Metis\research\data\dev\lance"

try:
    db = lancedb.connect(uri)
    table = db.open_table("metis_documents")
    print(f"✅ Success! Table found with {table.count_rows()} documents.")
    
    # Print the first row's metadata to see exactly how source/category are formatted
    if table.count_rows() > 0:
        first_doc = table.head(1).to_pandas().iloc[0]
        print(f"\nSample Metadata:")
        print(f"Title: {first_doc.get('title')}")
        print(f"Source: {first_doc.get('source')}")
        print(f"Category: {first_doc.get('category')}")
except Exception as e:
    print(f"❌ Error connecting to table: {e}")