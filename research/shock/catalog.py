"""
Historical shock event catalog for NG futures.

Sources (in priority order):
  1. Manual curated events — well-documented NG price dislocations since 2010
  2. FEMA disaster declarations API — winter storms, hurricanes (optional, graceful fallback)

Severity scale (from Event.md):
  1 = Elevated   : notable move, single market
  2 = Disruption : multi-market, recovers within weeks
  3 = Shock      : structural move, 1-3 month recovery
  4 = Crisis     : regime change, slow or no recovery

NG relevance:
  supply_shock   : production/pipeline/LNG outage -> bullish
  demand_shock   : extreme cold/heat -> bullish
  demand_collapse: COVID / warm winter -> bearish
  supply_glut    : storage surplus, new supply -> bearish
  macro           : broad energy market dislocation
"""
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "metis.db"

# Canonical NG price shocks, 2000-present
# Sources: EIA short-term energy outlooks, FERC reports, public record
MANUAL_EVENTS: list[dict] = [
    # ── Pre-shale era (2000-2009) ──────────────────────────────────────────────
    {
        "name": "2000-2001 Western Energy Crisis",
        "start": "2000-11-01", "end": "2001-04-30",
        "type": "demand_shock", "severity": 3, "source": "manual",
        "region": "nationwide",
        "description": (
            "Post-Y2K industrial boom + cold winter drove HH to $10/MMBtu. "
            "California rolling blackouts; tight supply before shale era. "
            "Marks the upper boundary of the pre-shale price regime."
        ),
    },
    {
        "name": "Iraq War / Winter 2003 Spike",
        "start": "2003-01-15", "end": "2003-03-31",
        "type": "macro", "severity": 2, "source": "manual",
        "region": "nationwide",
        "description": (
            "HH briefly hit $9.50 in Jan-Feb 2003. Prices driven primarily by "
            "cold winter and tight post-2001 supply, not the Iraq invasion directly "
            "(Iraq was not a US NG supplier). Iraq War (Mar 20) added macro risk "
            "premium but NG prices fell after the invasion as weather normalized."
        ),
    },
    {
        "name": "Hurricane Katrina + Rita",
        "start": "2005-08-25", "end": "2005-11-30",
        "type": "supply_shock", "severity": 4, "source": "manual",
        "region": "gulf_coast",
        "description": (
            "Katrina (Cat 5, Aug 29) then Rita (Cat 5, Sep 24) destroyed offshore "
            "platforms and pipelines in the Gulf of Mexico — the heart of US gas "
            "production at the time. HH spot spiked to $14+/MMBtu. ~1.5 Tcf/year "
            "of production capacity offline for months. Largest US supply shock "
            "before shale era. Permanently accelerated LNG import terminal buildout."
        ),
    },
    {
        "name": "2008 Financial Crisis + Demand Collapse",
        "start": "2008-07-01", "end": "2009-03-31",
        "type": "demand_collapse", "severity": 4, "source": "manual",
        "region": "nationwide",
        "description": (
            "NG peaked at $13.58 in July 2008 on oil correlation and tight supply, "
            "then collapsed to $4 by March 2009 as industrial demand cratered with "
            "the financial crisis. Shale gas (Haynesville, Marcellus) was ramping "
            "simultaneously — this event marks the structural onset of the shale "
            "supply surplus that defined the 2009-2020 low-price regime."
        ),
    },
    # ── Shale era (2010-2019) ──────────────────────────────────────────────────
    {
        "name": "Polar Vortex 2014",
        "start": "2014-01-05", "end": "2014-01-10",
        "type": "demand_shock", "severity": 3, "source": "manual",
        "region": "nationwide",
        "description": "Arctic air mass drove NG spot to $7+/MMBtu; demand records set across Midwest/Northeast",
    },
    {
        "name": "Crimea Annexation",
        "start": "2014-02-27", "end": "2014-05-31",
        "type": "macro", "severity": 1, "source": "manual",
        "region": "global",
        "description": (
            "Russia annexed Crimea (Feb 27, 2014); first Russia-Ukraine military conflict. "
            "HH impact was modest (~$1.87 swing) as US was not a gas exporter yet and "
            "shale supply was abundant. Primary impact was on European TTF and energy "
            "security policy. Marks the first observable Russia-Ukraine risk premium in "
            "global gas markets — predecessor to the 2022 full invasion."
        ),
    },
    {
        "name": "2016 Storage Glut",
        "start": "2016-03-01", "end": "2016-04-30",
        "type": "supply_glut", "severity": 1, "source": "manual",
        "region": "nationwide",
        "description": "Record storage levels post-warm winter pushed NG to $1.60 lows",
    },
    {
        "name": "Hurricane Harvey",
        "start": "2017-08-25", "end": "2017-09-15",
        "type": "supply_shock", "severity": 2, "source": "manual",
        "region": "gulf_coast",
        "description": "Category 4 landfall near Houston; refinery and gas processing shutdowns",
    },
    {
        "name": "Hurricane Michael",
        "start": "2018-10-10", "end": "2018-10-20",
        "type": "supply_shock", "severity": 2, "source": "manual",
        "region": "gulf_coast",
        "description": "Category 5 landfall in Florida panhandle; pipeline and distribution damage",
    },
    {
        "name": "Q4 2018 Price Spike",
        "start": "2018-11-01", "end": "2018-11-15",
        "type": "demand_shock", "severity": 2, "source": "manual",
        "region": "nationwide",
        "description": "Early winter cold + tight storage drove NG to $4.80; sharpest move since 2014",
    },
    # ── LNG export era (2020-present) ─────────────────────────────────────────
    {
        "name": "COVID Demand Collapse",
        "start": "2020-03-15", "end": "2020-05-31",
        "type": "demand_collapse", "severity": 3, "source": "manual",
        "region": "nationwide",
        "description": "Industrial shutdown and mild spring crushed NG demand; prices fell below $1.50",
    },
    {
        "name": "Winter Storm Uri",
        "start": "2021-02-10", "end": "2021-02-20",
        "type": "demand_shock", "severity": 4, "source": "manual",
        "region": "south_central",
        "description": "Texas grid failure; wellhead freeze-offs cut supply while demand surged; spot hit $24+",
    },
    {
        "name": "Hurricane Ida",
        "start": "2021-08-29", "end": "2021-09-15",
        "type": "supply_shock", "severity": 2, "source": "manual",
        "region": "gulf_coast",
        "description": "Category 4 landfall in Louisiana; 95%+ of Gulf of Mexico gas production offline",
    },
    {
        "name": "Freeport LNG Explosion",
        "start": "2022-06-08", "end": "2022-09-01",
        "type": "supply_glut", "severity": 3, "source": "manual",
        "region": "gulf_coast",
        "description": "2.0 bcf/d of LNG export capacity offline; US storage surged; HH fell ~40% from peak",
    },
    {
        "name": "Russia Invades Ukraine",
        "start": "2022-02-24", "end": "2022-06-30",
        "type": "macro", "severity": 4, "source": "manual",
        "region": "global",
        "description": "European gas crisis; TTF spiked; HH followed on LNG export demand surge",
    },
    {
        "name": "2022 Summer Peak",
        "start": "2022-07-01", "end": "2022-08-31",
        "type": "demand_shock", "severity": 3, "source": "manual",
        "region": "nationwide",
        "description": "Record heat + LNG export demand drove HH to $9.68 intraday; highest since 2008",
    },
    {
        "name": "Winter Storm Elliott",
        "start": "2022-12-22", "end": "2022-12-26",
        "type": "demand_shock", "severity": 3, "source": "manual",
        "region": "nationwide",
        "description": "Bomb cyclone; demand surge but production freeze-offs; basis spikes in Northeast",
    },
    {
        "name": "2023 Storage Rebuild",
        "start": "2023-02-01", "end": "2023-04-30",
        "type": "supply_glut", "severity": 1, "source": "manual",
        "region": "nationwide",
        "description": "Warm winter left storage bloated; NG fell below $2 through spring",
    },
    {
        "name": "Sabine Pass LNG Disruption",
        "start": "2023-12-22", "end": "2024-01-15",
        "type": "supply_glut", "severity": 1, "source": "manual",
        "region": "gulf_coast",
        "description": "Freeze-related LNG loading curtailments reduced export demand; domestic prices fell",
    },
    {
        "name": "2024 Winter Cold Snap",
        "start": "2024-01-10", "end": "2024-01-20",
        "type": "demand_shock", "severity": 2, "source": "manual",
        "region": "nationwide",
        "description": "Arctic blast drove demand spike; NG spiked briefly above $3.50",
    },
]


def fetch_fema_events(start_year: int = 2010) -> pd.DataFrame:
    """
    Fetch FEMA disaster declarations for NG-relevant incident types.
    Returns empty DataFrame if API is unavailable (503, timeout, etc.).
    """
    ng_types = ["Winter Storm", "Hurricane", "Severe Ice Storm", "Severe Freeze", "Typhoon", "Drought"]
    records = []

    for incident_type in ng_types:
        try:
            resp = requests.get(
                "https://www.fema.gov/api/open/v2/disasterDeclarations",
                params={
                    "$filter": f"incidentType eq '{incident_type}' and fyDeclared ge {start_year}",
                    "$top": 1000,
                    "$orderby": "declarationDate desc",
                    "$select": "disasterNumber,declarationDate,incidentBeginDate,incidentEndDate,state,incidentType,declarationTitle",
                },
                timeout=10,
            )
            if resp.status_code != 200:
                continue
            for rec in resp.json().get("DisasterDeclarations", []):
                records.append({
                    "name": f"FEMA: {rec.get('declarationTitle', incident_type)}",
                    "start": rec.get("incidentBeginDate", rec.get("declarationDate", ""))[:10],
                    "end": (rec.get("incidentEndDate") or rec.get("declarationDate", ""))[:10],
                    "type": _fema_type_map(incident_type),
                    "severity": _fema_severity(incident_type),
                    "source": "fema",
                    "region": rec.get("state", "unknown"),
                    "description": f"FEMA declared disaster #{rec.get('disasterNumber')} — {rec.get('declarationTitle')}",
                })
        except Exception:
            continue  # API down or network issue; skip silently

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    # Deduplicate: one event per (name_prefix, start_date) — FEMA issues per-state declarations
    df["_key"] = df["start"].str[:7] + "|" + df["type"]
    df = df.drop_duplicates(subset="_key").drop(columns="_key")
    return df


def _fema_type_map(incident_type: str) -> str:
    return {
        "Winter Storm": "demand_shock",
        "Hurricane": "supply_shock",
        "Typhoon": "supply_shock",
        "Severe Ice Storm": "demand_shock",
        "Severe Freeze": "demand_shock",
        "Drought": "macro",
    }.get(incident_type, "macro")


def _fema_severity(incident_type: str) -> int:
    return {"Winter Storm": 2, "Hurricane": 2, "Typhoon": 2,
            "Severe Ice Storm": 2, "Severe Freeze": 2, "Drought": 1}.get(incident_type, 1)


def build_catalog(include_fema: bool = True) -> pd.DataFrame:
    """Merge manual events and (optionally) FEMA into a unified catalog DataFrame."""
    manual = pd.DataFrame(MANUAL_EVENTS)

    if include_fema:
        fema = fetch_fema_events()
        if not fema.empty:
            df = pd.concat([manual, fema], ignore_index=True)
        else:
            df = manual.copy()
    else:
        df = manual.copy()

    df["start"] = pd.to_datetime(df["start"])
    df["end"]   = pd.to_datetime(df["end"])
    df = df.sort_values("start").reset_index(drop=True)
    return df


def write_catalog_to_db(catalog: pd.DataFrame, conn: sqlite3.Connection) -> None:
    catalog_out = catalog.copy()
    catalog_out["start"] = catalog_out["start"].dt.strftime("%Y-%m-%d")
    catalog_out["end"]   = catalog_out["end"].dt.strftime("%Y-%m-%d")
    catalog_out.to_sql("shock_events", conn, if_exists="replace", index=True, index_label="id")
    print(f"  Wrote {len(catalog_out)} events to shock_events table")
