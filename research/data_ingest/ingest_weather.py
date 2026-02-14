"""
Weather ingestion using Open-Meteo (no API key required).
- Targets Henry Hub, LA and Cushing, OK (core NG hubs).
- Pulls daily history and computes HDD/CDD.
- Writes to weather_observations table with upsert on (date, location).

Usage (REAL mode):
    METIS_MODE=REAL python research/data_ingest/ingest_weather.py --start 2023-01-01 --end 2026-01-09

In DEV mode, skips API calls and prints a notice.
"""
import argparse
import os
from datetime import datetime, date, timezone, timedelta
from typing import List, Dict, Any

import pandas as pd
import requests
from sqlalchemy import create_engine, text

from research.common import runtime_config as rc

DB_URL = rc.get_db_url("sqlite:///data/metis.db")

# Core hubs
LOCATIONS = {
    "henry_hub_la": {"lat": 29.9936, "lon": -92.1480},
    "cushing_ok": {"lat": 35.9853, "lon": -96.7675},
}

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"


def to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def to_inches(mm: float) -> float:
    return mm / 25.4


def to_mph(kmh: float) -> float:
    return kmh * 0.621371


def compute_hdd_cdd(temp_f: pd.Series, base: float = 65.0) -> pd.DataFrame:
    hdd = (base - temp_f).clip(lower=0)
    cdd = (temp_f - base).clip(lower=0)
    return pd.DataFrame({"hdd": hdd, "cdd": cdd})


def fetch_weather(location: str, lat: float, lon: float, start: date, end: date) -> pd.DataFrame:
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": [
            "temperature_2m_mean",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "snowfall_sum",
            "wind_speed_10m_max",
        ],
        "timezone": "UTC",
    }
    resp = requests.get(OPEN_METEO_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    daily = data.get("daily", {})
    if not daily:
        return pd.DataFrame()

    df = pd.DataFrame(daily)
    df.rename(columns={
        "time": "date",
        "temperature_2m_mean": "temp_mean_c",
        "temperature_2m_max": "temp_max_c",
        "temperature_2m_min": "temp_min_c",
        "precipitation_sum": "precip_mm",
        "snowfall_sum": "snow_mm",
        "wind_speed_10m_max": "wind_kmh",
    }, inplace=True)

    # Unit conversions
    df["temp_mean_f"] = df["temp_mean_c"].apply(to_f)
    df["temp_max_f"] = df["temp_max_c"].apply(to_f)
    df["temp_min_f"] = df["temp_min_c"].apply(to_f)
    df["precip_in"] = df["precip_mm"].apply(to_inches)
    df["snow_in"] = df["snow_mm"].apply(to_inches)
    df["wind_max_mph"] = df["wind_kmh"].apply(to_mph)

    hdd_cdd = compute_hdd_cdd(df["temp_mean_f"])
    df = pd.concat([df, hdd_cdd], axis=1)

    df["location"] = location
    df["date"] = pd.to_datetime(df["date"])
    df["timestamp"] = df["date"]
    df["source"] = "open-meteo"
    df["created_at"] = datetime.now(timezone.utc)

    keep_cols = [
        "timestamp",
        "location",
        "temp_mean_f",
        "temp_min_f",
        "temp_max_f",
        "wind_max_mph",
        "precip_in",
        "snow_in",
        "hdd",
        "cdd",
        "source",
        "created_at",
    ]
    return df[keep_cols]


def ensure_table(engine) -> None:
    create_sql = """
    CREATE TABLE IF NOT EXISTS weather_observations (
        timestamp TIMESTAMP NOT NULL,
        location TEXT NOT NULL,
        temp_mean_f REAL,
        temp_min_f REAL,
        temp_max_f REAL,
        wind_max_mph REAL,
        precip_in REAL,
        snow_in REAL,
        hdd REAL,
        cdd REAL,
        source TEXT,
        created_at TIMESTAMP,
        UNIQUE(timestamp, location)
    );
    """
    with engine.begin() as conn:
        conn.execute(text(create_sql))


def upsert_weather(engine, df: pd.DataFrame) -> None:
    if df.empty:
        return
    ensure_table(engine)
    # SQLite upsert
    insert_sql = """
    INSERT INTO weather_observations (
        timestamp, location, temp_mean_f, temp_min_f, temp_max_f,
        wind_max_mph, precip_in, snow_in, hdd, cdd, source, created_at
    ) VALUES (:timestamp, :location, :temp_mean_f, :temp_min_f, :temp_max_f,
              :wind_max_mph, :precip_in, :snow_in, :hdd, :cdd, :source, :created_at)
    ON CONFLICT(timestamp, location) DO UPDATE SET
        temp_mean_f=excluded.temp_mean_f,
        temp_min_f=excluded.temp_min_f,
        temp_max_f=excluded.temp_max_f,
        wind_max_mph=excluded.wind_max_mph,
        precip_in=excluded.precip_in,
        snow_in=excluded.snow_in,
        hdd=excluded.hdd,
        cdd=excluded.cdd,
        source=excluded.source,
        created_at=excluded.created_at;
    """
    # Convert pandas Timestamps to python datetime for SQLite binding
    records: List[Dict[str, Any]] = df.to_dict(orient="records")
    for rec in records:
        ts = rec.get("timestamp")
        if hasattr(ts, "to_pydatetime"):
            rec["timestamp"] = ts.to_pydatetime()
        ca = rec.get("created_at")
        if hasattr(ca, "to_pydatetime"):
            rec["created_at"] = ca.to_pydatetime()
    with engine.begin() as conn:
        conn.execute(text(insert_sql), records)


def main(start: str = None, end: str = None) -> None:
    """
    Ingest weather data from Open-Meteo.
    
    Args:
        start: Start date in ISO format (YYYY-MM-DD). Defaults to 7 days ago.
        end: End date in ISO format (YYYY-MM-DD). Defaults to today.
    """
    rc.log_mode("Weather")
    if not rc.require_real_mode("Open-Meteo weather"):
        return

    # Default to last 7 days if not specified
    if end is None:
        end = datetime.now(timezone.utc).date().isoformat()
    if start is None:
        start = (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()

    start_date = datetime.fromisoformat(start).date()
    end_date = datetime.fromisoformat(end).date()

    engine = create_engine(DB_URL)
    all_records = []
    for loc, coords in LOCATIONS.items():
        print(f"[WEATHER] Fetching {loc} from {start_date} to {end_date}")
        df = fetch_weather(loc, coords["lat"], coords["lon"], start_date, end_date)
        print(f"[WEATHER] Retrieved {len(df)} rows for {loc}")
        all_records.append(df)

    combined = pd.concat(all_records, axis=0, ignore_index=True) if all_records else pd.DataFrame()
    if combined.empty:
        print("[WEATHER] No data fetched")
        return

    upsert_weather(engine, combined)
    print(f"[WEATHER] Upserted {len(combined)} rows into weather_observations")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest weather data from Open-Meteo")
    parser.add_argument("--start", default="2023-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=datetime.now(timezone.utc).date().isoformat(), help="End date (YYYY-MM-DD)")
    args = parser.parse_args()
    main(args.start, args.end)
