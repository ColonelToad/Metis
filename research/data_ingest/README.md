# Multi-Source Data Ingestion Pipeline

This directory contains ingestion scripts for heterogeneous alternative data sources.

## Data Sources by Category

### Energy & Grid (Covered)
- **EIA:** Natural gas storage + production (`ingest_eia.py`)
- **Grid LMP:** Real-time electricity prices via gridstatus (`ingest_lmp.py`)
- **Ember:** Global energy data (API key available)

### Policy & Macro (Covered)
- **FRED:** Macro indicators (`ingest_fred.py`)
- **Congress.gov:** Legislative data (API key available)
- **Finnhub:** Congressional trades (`ingest_congress_trades.py`)

### Supply Chain (Partial)
- **Maritime AIS:** LNG tanker tracking (`ingest_ais_maritime.py`)
  - Requires MarineTraffic API key (free tier: 50 calls/day)
  - Alternative: AISHub.net (free but lower coverage)

### Labor Market (Partial)
- **Job Postings:** Energy sector hiring (`ingest_job_postings.py`)
  - Uses Adzuna API (free tier: 3000 calls/month)
  - Get key: https://developer.adzuna.com/

## Missing Data Categories (Free Alternatives)

### Traffic/Mobility
**Option 1: Census OnTheMap API**
- Tracks commute patterns at county level
- Free, no API key required
- Lead indicator for regional economic activity

**Option 2: Google Popular Times (via SerpAPI)**
- Free tier: 100 searches/month
- Track retail foot traffic at specific locations

### Additional Supply Chain
**USDA Agricultural Marketing Service**
- Commodity shipment volumes (grain, meat)
- Free API, correlates with trucking demand

## Running the Pipeline

### Install Dependencies
```bash
pip install gridstatus requests pandas sqlalchemy psycopg2-binary python-dotenv
```

### Runtime Modes (API usage control)
- `METIS_MODE=DEV` (default): **No external API calls**; scripts skip network and use synthetic/fallback data.
- `METIS_MODE=REAL`: Call APIs when keys are present; writes real data to DB/Parquet.

Set in `.env` or environment:
```bash
set METIS_MODE=DEV   # Windows PowerShell example
# or
export METIS_MODE=REAL
```

### Set Environment Variables
Add missing API keys to `.env`:
```bash
ADZUNA_APP_ID=your_id_here
ADZUNA_API_KEY=your_key_here
MARINETRAFFIC_API_KEY=your_key_here
DB_URL=postgresql://postgres:postgres@localhost:5432/metis
```

### Run Individual Ingesters
```bash
cd research
python data_ingest/ingest_eia.py
python data_ingest/ingest_lmp.py
python data_ingest/ingest_fred.py
python data_ingest/ingest_congress_trades.py
python data_ingest/ingest_job_postings.py  # Requires Adzuna key
python data_ingest/ingest_ais_maritime.py  # Requires MarineTraffic key
```

### Run All (Scheduled)
Create a cron job or Windows Task Scheduler to run daily:
```bash
python data_ingest/run_all_ingesters.py
```

## Data Quality Checks

After ingestion, validate:
1. No gaps in timestamps
2. Reasonable value ranges
3. Correlation matrix shows expected relationships

Run validation:
```bash
python data_ingest/validate_ingestion.py
```

## Next Steps (Week 2)

1. Add Census OnTheMap ingestion for mobility data
2. Implement data quality monitoring
3. Compute correlation matrix: each source vs NG price returns
4. Document lead/lag relationships (which sources predict price 1-6 hours ahead)
5. Build unified feature table for ML pipeline
