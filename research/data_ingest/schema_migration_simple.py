"""
Database Schema Migration - Simple Version
Creates tables for new data sources in SQLite
"""
import sqlite3
import os

DB_PATH = "data/metis.db"

# SQL schema for new tables
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS fema_disasters (
    id TEXT PRIMARY KEY,
    state TEXT,
    declaration_type TEXT,
    incident_type TEXT,
    declaration_date TIMESTAMP,
    incident_begin_date TIMESTAMP,
    incident_end_date TIMESTAMP,
    title TEXT,
    ihp_program_declared BOOLEAN,
    iap_program_declared BOOLEAN,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fema_state_date ON fema_disasters(state, declaration_date);

CREATE TABLE IF NOT EXISTS storm_events (
    event_id TEXT PRIMARY KEY,
    state TEXT,
    county TEXT,
    event_type TEXT,
    begin_date TIMESTAMP,
    end_date TIMESTAMP,
    property_damage FLOAT,
    crop_damage FLOAT,
    injuries_direct INTEGER,
    deaths_direct INTEGER,
    magnitude FLOAT,
    magnitude_type TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_storm_state_date ON storm_events(state, begin_date);

CREATE TABLE IF NOT EXISTS drought_conditions (
    id TEXT PRIMARY KEY,
    state TEXT,
    date TIMESTAMP,
    drought_category_none FLOAT,
    drought_category_d0 FLOAT,
    drought_category_d1 FLOAT,
    drought_category_d2 FLOAT,
    drought_category_d3 FLOAT,
    drought_category_d4 FLOAT,
    drought_severity_index FLOAT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_drought_state_date ON drought_conditions(state, date);

CREATE TABLE IF NOT EXISTS census_building_permits (
    id TEXT PRIMARY KEY,
    date TIMESTAMP,
    state TEXT,
    county TEXT,
    permit_count INTEGER,
    permit_valuation FLOAT,
    units_issued INTEGER,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_permits_state_date ON census_building_permits(state, date);

CREATE TABLE IF NOT EXISTS aviation_fuel (
    id TEXT PRIMARY KEY,
    date TIMESTAMP,
    carrier TEXT,
    fuel_gallons BIGINT,
    fuel_cost FLOAT,
    cost_per_gallon FLOAT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_aviation_fuel_date ON aviation_fuel(date);

CREATE TABLE IF NOT EXISTS aviation_ontime (
    id TEXT PRIMARY KEY,
    date TIMESTAMP,
    carrier TEXT,
    avg_dep_delay FLOAT,
    avg_arr_delay FLOAT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_aviation_ontime_date ON aviation_ontime(date);

CREATE TABLE IF NOT EXISTS scfi_freight_rates (
    id TEXT PRIMARY KEY,
    date TIMESTAMP,
    route TEXT,
    rate_usd_per_teu INTEGER,
    week_over_week_change FLOAT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scfi_date ON scfi_freight_rates(date);

CREATE TABLE IF NOT EXISTS port_la_lb_stats (
    id TEXT PRIMARY KEY,
    date TIMESTAMP,
    port TEXT,
    teus FLOAT,
    teus_yoy_change FLOAT,
    teus_ma3 FLOAT,
    teus_deviation FLOAT,
    supply_chain_stress INTEGER,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_port_stats_date ON port_la_lb_stats(date, port);

CREATE TABLE IF NOT EXISTS ng_futures_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TIMESTAMP UNIQUE NOT NULL,
    open FLOAT,
    high FLOAT,
    low FLOAT,
    close FLOAT,
    volume INTEGER,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ng_futures_date ON ng_futures_daily(date);

CREATE TABLE IF NOT EXISTS cme_futures_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TIMESTAMP NOT NULL,
    contract_type TEXT NOT NULL,
    symbol TEXT NOT NULL,
    contract_name TEXT,
    open FLOAT,
    high FLOAT,
    low FLOAT,
    close FLOAT,
    volume INTEGER,
    return_1d FLOAT,
    volatility_20d FLOAT,
    ma_20 FLOAT,
    ma_200 FLOAT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, contract_type)
);

CREATE INDEX IF NOT EXISTS idx_cme_futures_date_contract ON cme_futures_daily(date, contract_type);
CREATE INDEX IF NOT EXISTS idx_cme_futures_contract ON cme_futures_daily(contract_type);

CREATE TABLE IF NOT EXISTS grid_lmp_multi_iso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP NOT NULL,
    iso TEXT NOT NULL,
    node_id TEXT NOT NULL,
    node_type TEXT,
    location_name TEXT,
    market TEXT,
    lmp FLOAT,
    energy_component FLOAT,
    congestion_component FLOAT,
    loss_component FLOAT,
    data_fetch_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(timestamp, iso, node_id)
);

CREATE INDEX IF NOT EXISTS idx_grid_lmp_timestamp_iso ON grid_lmp_multi_iso(timestamp, iso);
CREATE INDEX IF NOT EXISTS idx_grid_lmp_iso_node ON grid_lmp_multi_iso(iso, node_id);
CREATE INDEX IF NOT EXISTS idx_grid_lmp_timestamp ON grid_lmp_multi_iso(timestamp);

CREATE TABLE IF NOT EXISTS grid_lmp (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP NOT NULL,
    lmp FLOAT,
    node_id TEXT,
    iso TEXT DEFAULT 'CAISO',
    data_fetch_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(timestamp, node_id, iso)
);

CREATE INDEX IF NOT EXISTS idx_grid_lmp_timestamp_iso_compat ON grid_lmp(timestamp, iso);
"""

def create_schema():
    """Create all tables if they don't exist"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Split SQL by semicolons and execute each statement
        for statement in SCHEMA_SQL.split(';'):
            if statement.strip():
                cursor.execute(statement)
        
        conn.commit()
        
        # Verify tables created
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        )
        tables = cursor.fetchall()
        
        print(f"\n✓ All tables in database:")
        for table in tables:
            print(f"  - {table[0]}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"✗ Error creating schema: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print(f"Creating new data source tables in {DB_PATH}...")
    if create_schema():
        print("\n✓ Schema migration complete!")
    else:
        print("\n✗ Schema migration failed!")
