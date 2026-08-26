"""
Implementation-Friction Ratio v0 ("law on paper vs law in reality")

Quantifies where national policy tailwinds fail to become physical capacity,
by state x technology, from a single authoritative source: LBNL's Queued Up
interconnection-queue dataset (project-level records through end-2025).

Metrics per state x tech (cohort = projects entering queue since --since):
    gw_operational   capacity that reached COD
    gw_active        still waiting (pipeline)
    gw_withdrawn     capacity that gave up / was blocked
    gw_suspended
    realized_share   operational / (operational + withdrawn)
                     -- of finished attempts, fraction that survived
    med_months_cod   median months from request to COD (operational only)

A state can have stellar paper policy and still show low realized_share +
long COD times: that divergence IS implementation friction, measured.

Source file cached at data/cache/lbnl/queued_up_2026.xlsx (CC BY 4.0,
LBL). Re-download manually when the annual edition drops.

USAGE:
    python research/features/build_friction_ratio.py [--since 2015]
"""

import argparse
import logging
import os
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv("DB_URL", "sqlite:///data/metis.db").replace("sqlite:///", "")

XLSX_URL = (
    "https://eta-publications.lbl.gov/sites/default/files/"
    "2026-05/lbnl_ix_queue_data_file_thru2025.xlsx"
)
CACHE = Path("data/cache/lbnl/queued_up_2026.xlsx")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

STATE_ABBR = {
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "Florida": "FL",
    "Georgia": "GA",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
}


def ensure_cached() -> Path:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if not CACHE.exists():
        logger.info(f"Downloading LBNL queue file -> {CACHE}")
        r = requests.get(XLSX_URL, timeout=300)
        r.raise_for_status()
        CACHE.write_bytes(r.content)
    return CACHE


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--since", type=int, default=2015, help="cohort: projects entering queue this year onward"
    )
    args = parser.parse_args()

    path = ensure_cached()
    df = pd.read_excel(path, sheet_name="03. Complete Queue Data", header=1)
    logger.info(f"Queue rows: {len(df)}")

    for c in ("q_date", "on_date", "wd_date"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["mw_total"] = df[["mw_1", "mw_2", "mw_3"]].fillna(0).sum(axis=1)
    df["state_abbr"] = df["state"].map(STATE_ABBR).fillna(df["state"])
    df["q_year"] = df["q_date"].dt.year

    coh = df[df["q_year"] >= args.since].copy()
    logger.info(
        f"Cohort >= {args.since}: {len(coh)} projects, " f"{coh['mw_total'].sum()/1000:.0f} GW"
    )

    def agg(g: pd.DataFrame) -> pd.Series:
        op = g[g["q_status"] == "operational"]
        wd = g[g["q_status"].isin(["withdrawn", "suspended"])]
        act = g[g["q_status"] == "active"]
        months = (op["on_date"] - op["q_date"]).dt.days / 30.44
        out = pd.Series(
            {
                "gw_operational": op["mw_total"].sum() / 1000,
                "gw_active": act["mw_total"].sum() / 1000,
                "gw_withdrawn_susp": wd["mw_total"].sum() / 1000,
                "realized_share": (
                    op["mw_total"].sum() / max(op["mw_total"].sum() + wd["mw_total"].sum(), 1e-9)
                ),
                "median_months_to_cod": months.median(),
                "n_projects": len(g),
            }
        )
        return out

    grp = coh.groupby(["state_abbr", "type_clean"]).apply(agg, include_groups=False).reset_index()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS interconnection_queue_friction (
            state TEXT NOT NULL, tech TEXT NOT NULL, cohort_since INTEGER NOT NULL,
            gw_operational REAL, gw_active REAL, gw_withdrawn_susp REAL,
            realized_share REAL, median_months_to_cod REAL, n_projects INTEGER,
            PRIMARY KEY (state, tech, cohort_since))""")
    now = pd.Timestamp.utcnow().isoformat(timespec="seconds")
    rows = [
        (
            r.state_abbr,
            r.type_clean,
            args.since,
            float(r.gw_operational),
            float(r.gw_active),
            float(r.gw_withdrawn_susp),
            float(r.realized_share),
            None if pd.isna(r.median_months_to_cod) else float(r.median_months_to_cod),
            int(r.n_projects),
        )
        for r in grp.itertuples(index=False)
    ]
    conn.executemany(
        """INSERT OR REPLACE INTO interconnection_queue_friction
           VALUES (?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    conn.close()
    logger.info(f"Wrote {len(rows)} state-tech rows")

    # Spotlight: shortlist states, solar + battery
    spotlight_states = ["TX", "PA", "OH", "WV", "CA", "NY", "CO", "ND", "IA", "AZ"]
    spot = grp[
        (grp["state_abbr"].isin(spotlight_states))
        & (grp["type_clean"].isin(["Solar", "Battery", "Gas"]))
    ]
    cols = [
        "state_abbr",
        "type_clean",
        "gw_operational",
        "gw_active",
        "gw_withdrawn_susp",
        "realized_share",
        "median_months_to_cod",
    ]
    print("\n=== Shortlist spotlight ===")
    print(spot[cols].sort_values(["type_clean", "realized_share"]).to_string(index=False))


if __name__ == "__main__":
    main()
