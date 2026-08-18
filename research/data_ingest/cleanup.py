import sys
from pathlib import Path
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parents[2]))
from research.common import runtime_config as rc

def main():
    load_dotenv()
    DB_URL = rc.get_db_url()
    engine = create_engine(DB_URL)
    
    with engine.begin() as conn:
        # Delete the rows formatted with the 'T'
        res1 = conn.execute(text("DELETE FROM eia_storage WHERE timestamp LIKE '%T%'"))
        res2 = conn.execute(text("DELETE FROM eia_production WHERE timestamp LIKE '%T%'"))
        res3 = conn.execute(text("DELETE FROM fred_macro WHERE timestamp LIKE '%T%'"))
        
        print(f"Deleted {res1.rowcount} 'T' rows from eia_storage")
        print(f"Deleted {res2.rowcount} 'T' rows from eia_production")
        print(f"Deleted {res3.rowcount} 'T' rows from fred_macro")

if __name__ == "__main__":
    main()