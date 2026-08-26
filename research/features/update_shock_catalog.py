"""
One-time catalog update: creates rejected_events table, adds new events,
applies reclassifications, removes Crimea, fixes Freeport type.
Idempotent -- safe to run multiple times.

Run from C:\\Users\\legot\\Metis:
    python research/features/update_shock_catalog.py
"""

import os
from datetime import date

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
engine = create_engine(DB_URL)

# ── 1. Inspect current source values so new entries are consistent ────────────
with engine.connect() as conn:
    sources = conn.execute(
        text("SELECT DISTINCT source FROM shock_events WHERE source IS NOT NULL")
    ).fetchall()
    print("Existing source values:", [r[0] for r in sources])

TODAY = str(date.today())

NEW_EVENTS = [
    # ── Type 1: endogenous buildable precursor ────────────────────────────────
    {
        "name": "2014-2016 Shale Oversupply / Oil Price Collapse",
        "start": "2014-06-01",
        "end": "2016-02-28",
        "type": "supply_glut",
        "severity": 4,
        "source": "manual",
        "region": "nationwide",
        "description": (
            "WTI crude fell from $107 (Jun 2014) to $26 (Feb 2016) as US shale "
            "production ramped for 18+ months while OPEC refused to cut at the "
            "Nov 2014 Vienna meeting. NG price followed crude with a measurable lag. "
            "EIA production data showed the supply build well before the price break -- "
            "strongest Type 1 candidate after 2008 for OMD precursor testing. "
            "The existing '2016 Storage Glut' entry captures only the symptom; "
            "this entry captures the full oversupply cycle."
        ),
    },
    {
        "name": "Post-2020 LNG Export Capacity Buildout (ongoing)",
        "start": "2023-01-01",
        "end": None,  # open
        "type": "transition_period",
        "severity": 2,
        "source": "manual",
        "region": "nationwide",
        "description": (
            "Plaquemines (Dec 2024), Golden Pass (Apr 2026), Port Arthur and CP2 "
            "under construction. Export capacity additions running ahead of contracted "
            "demand. Early signs of a supply-side cycle similar to 2014-2016 for LNG "
            "specifically. The endogenous fragility component (overbuild relative to "
            "demand growth) is building now -- not yet a crisis, but a live precursor "
            "period for OMD monitoring."
        ),
    },
    # ── Type 2: exogenous interrupt, aftermath measurement ────────────────────
    {
        "name": "2003 Northeast Blackout",
        "start": "2003-08-14",
        "end": "2003-08-16",
        "type": "supply_shock",
        "severity": 3,
        "source": "manual",
        "region": "northeast",
        "description": (
            "Largest blackout in North American history: 55 million people across "
            "the US Northeast and Canada. Caused by a software bug in FirstEnergy's "
            "alarm system triggering cascade failure. Directly led to mandatory NERC "
            "reliability standards (Energy Policy Act 2005) and transmission investment "
            "that installed a new regulatory baseline still operative today. "
            "Clean Type 2: exogenous trigger (software failure), measurable aftermath "
            "(NERC CIP standards). Not NG-specific but foundational for energy infra "
            "resilience framing."
        ),
    },
    {
        "name": "2011 Southwest Blackout",
        "start": "2011-09-08",
        "end": "2011-09-08",
        "type": "supply_shock",
        "severity": 2,
        "source": "manual",
        "region": "southwest",
        "description": (
            "Single worker error at an Arizona Public Service substation cascaded "
            "into a 12-hour blackout affecting 2.7M people across Arizona, California, "
            "and Baja California. Exposed inadequate situational awareness and "
            "inter-utility coordination gaps -- the same failure modes the 2003 "
            "blackout was supposed to have fixed. The recurrence of an 'already fixed' "
            "failure mode is directly relevant to the assumption-archaeology framework: "
            "the new baseline installed by 2003 was shallower than it appeared."
        ),
    },
    {
        "name": "Fukushima Daiichi Nuclear Disaster",
        "start": "2011-03-11",
        "end": "2013-12-16",
        "type": "transition_period",
        "severity": 5,
        "source": "manual",
        "region": "global",
        "description": (
            "Earthquake/tsunami triggered meltdowns at Fukushima Daiichi, leading to "
            "a nationwide Japanese nuclear shutdown (30% of electricity generation to "
            "near-zero). Japan became the world's largest LNG importer almost overnight; "
            "JKM-TTF and JKM-HH spreads decoupled for years. Unlike BP Deepwater "
            "Horizon (which did not measurably change crude use patterns), Fukushima "
            "permanently restructured global LNG demand -- the new Japanese import "
            "baseline installed post-Fukushima has not reverted. "
            "Type 3: exogenous trigger (earthquake) landing on a system with known "
            "single-point-of-failure fragility from concentrated nuclear dependence. "
            "Aftermath (z) extends to present -- Japanese reactor restarts remain "
            "incomplete and each restart measurably moves JKM pricing."
        ),
    },
    {
        "name": "Colonial Pipeline Ransomware Attack",
        "start": "2021-05-07",
        "end": "2021-05-12",
        "type": "supply_shock",
        "severity": 3,
        "source": "manual",
        "region": "east_coast",
        "description": (
            "DarkSide ransomware shut down 5,500 miles of pipeline delivering 45% "
            "of East Coast fuel supply for six days. Caused panic buying and regional "
            "fuel shortages across the Southeast. Refined products (not NG) but exposes "
            "identical critical infrastructure concentration risk. "
            "Aftermath installed new baseline: CISA pipeline security directives, TSA "
            "cybersecurity requirements for pipeline operators. First major "
            "cyber-physical attack on US energy infrastructure with documented "
            "supply consequences."
        ),
    },
    # ── Transition periods ─────────────────────────────────────────────────────
    {
        "name": "Obama-Era Clean Energy Transition",
        "start": "2009-02-17",
        "end": "2015-12-12",
        "type": "transition_period",
        "severity": 3,
        "source": "manual",
        "region": "nationwide",
        "description": (
            "Three anchors define this period: ARRA (Feb 17 2009, $90B clean energy "
            "investment), EPA Clean Power Plan (finalized Aug 3 2015, first federal "
            "rule capping existing power plant carbon emissions), and Paris Agreement "
            "(Dec 12 2015). Collectively accelerated coal-plant retirements and "
            "established gas as the bridge fuel -- measurable in utility capex, "
            "FERC interconnection queues, and the coal retirement curve. "
            "Type 1: policy-induced endogenous transition. Did not move NG prices "
            "violently week-to-week but permanently reshuffled the buyer composition "
            "(industrial/heating -> power generation) and installed the structural "
            "gas demand floor that persists today."
        ),
    },
    {
        "name": "AI Data Center Power Demand Surge (ongoing)",
        "start": "2024-01-01",
        "end": None,  # open
        "type": "transition_period",
        "severity": 3,
        "source": "manual",
        "region": "nationwide",
        "description": (
            "Three concrete anchors: IEA Jan 2024 Electricity report first documented "
            "data center demand as measurable non-trivial fraction of US power demand "
            "projected to double by 2026; Dominion Energy Northern Virginia "
            "interconnection queue backlog (2023-present) appearing in FERC reliability "
            "assessments; hyperscaler long-term PPAs with nuclear/gas generators "
            "bypassing the utility layer (2023-2024). "
            "Type 3: AI compute demand (exogenous trigger) arriving faster than any "
            "planning cycle anticipated, landing on a grid with documented zero-slack "
            "in transmission interconnection, transformer manufacturing, and skilled "
            "labor -- same structure as 2005 refinery capacity crisis. "
            "The endogenous fragility (queue backlogs, manufacturing bottlenecks) was "
            "building before the demand shock hit it. Open entry -- regime actively evolving."
        ),
    },
    {
        "name": "Russia-Ukraine + Iran/Hormuz Overlap Period (ongoing)",
        "start": "2022-02-24",
        "end": None,  # open
        "type": "macro",
        "severity": 5,
        "source": "manual",
        "region": "global",
        "description": (
            "Two concurrent Type 3 events with overlapping (w,z) radii -- the hardest "
            "test case for the OMD multimodal framework. "
            "Russia-Ukraine: exogenous trigger (invasion) landing on measurable "
            "European gas dependence fragility (EU storage already at record lows "
            "pre-invasion, Gazprom withholding flows from late 2021). "
            "Iran/Hormuz: separate geopolitical trigger with its own endogenous "
            "fragility component (Hormuz Strait concentration risk in global LNG "
            "routing, approximately 20% of global gas supply transits). "
            "The analytical challenge: disentangling which source's signal is "
            "responding to which event when both are active simultaneously. "
            "This overlap period is the primary test of whether the (w,z) per-source "
            "radius approach can separate co-occurring shocks."
        ),
    },
]

RECLASSIFICATIONS = [
    # Freeport LNG Explosion: supply_glut -> supply_disruption
    {
        "id": 14,
        "type": "supply_disruption",
        "description": (
            "Explosion knocked out 20% of US LNG export capacity for ~3 months. "
            "Tightened global LNG market (less US supply) while temporarily lowering "
            "domestic NG prices (less gas leaving = more available domestically). "
            "Reclassified from supply_glut -- the original label was backwards; "
            "this was a supply disruption that caused a domestic glut as a side effect, "
            "not a glut event in itself."
        ),
    },
]

REMOVALS = [
    # Crimea Annexation: near-zero effect on US NG markets in 2014
    {
        "id": 5,
        "reason": "Near-zero measurable effect on US NG markets in 2014. US was not exporting LNG to Europe at the time; European gas dependence on Russia was not yet transmitted to Henry Hub pricing. Relevant as a precursor to the 2022 Ukraine entry but not as a standalone US energy shock. The 2022 Russia-Ukraine + Iran/Hormuz entry captures the period when this dependence actually mattered to US markets.",
    },
]

REJECTED_EVENTS = [
    {
        "name": "BP Deepwater Horizon Oil Spill",
        "description": "Largest marine oil spill in history (April 20 - September 19, 2010). Killed 11 workers, released 4.9M barrels of crude into the Gulf of Mexico.",
        "reason": "Did not measurably change crude oil use patterns -- the key distinction from Fukushima, which permanently restructured global LNG demand. Oil consumption continued on its pre-spill trajectory after cleanup. Infrastructure failure with enormous environmental consequence but no durable energy transition signal.",
        "considered_date": TODAY,
    },
    {
        "name": "Crimea Annexation (2014)",
        "description": "Russia annexed Crimea February 27 - March 18, 2014. Triggered Western sanctions and early European concern about Russian gas dependence.",
        "reason": "Removed from shock_events catalog. Near-zero measurable effect on US NG markets in 2014 -- US was not yet exporting LNG to Europe, so European gas dependence on Russia was not transmitted to Henry Hub. Retained as a precursor note in the 2022 Russia-Ukraine catalog entry.",
        "considered_date": TODAY,
    },
]


def run():
    with engine.begin() as conn:

        # ── Create rejected_events table ──────────────────────────────────────
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS rejected_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                reason TEXT NOT NULL,
                considered_date TEXT
            )
        """))
        print("rejected_events table ready")

        # ── Insert rejected events (skip if already present by name) ──────────
        for ev in REJECTED_EVENTS:
            exists = conn.execute(
                text("SELECT COUNT(*) FROM rejected_events WHERE name=:name"), {"name": ev["name"]}
            ).scalar()
            if not exists:
                conn.execute(
                    text("""
                    INSERT INTO rejected_events (name, description, reason, considered_date)
                    VALUES (:name, :description, :reason, :considered_date)
                """),
                    ev,
                )
                print(f"  Rejected: {ev['name']}")
            else:
                print(f"  Already present in rejected_events: {ev['name']}")

        # ── Remove events ─────────────────────────────────────────────────────
        for r in REMOVALS:
            row = conn.execute(
                text("SELECT name FROM shock_events WHERE id=:id"), {"id": r["id"]}
            ).fetchone()
            if row:
                conn.execute(text("DELETE FROM shock_events WHERE id=:id"), {"id": r["id"]})
                print(f"  Removed: [{r['id']}] {row[0]}")
            else:
                print(f"  Already removed: id={r['id']}")

        # ── Reclassify events ─────────────────────────────────────────────────
        for r in RECLASSIFICATIONS:
            row = conn.execute(
                text("SELECT name FROM shock_events WHERE id=:id"), {"id": r["id"]}
            ).fetchone()
            if row:
                conn.execute(
                    text("""
                    UPDATE shock_events SET type=:type, description=:description
                    WHERE id=:id
                """),
                    r,
                )
                print(f"  Reclassified: [{r['id']}] {row[0]} -> type={r['type']}")
            else:
                print(f"  Not found for reclassification: id={r['id']}")

        # ── Insert new events (skip if name already exists) ───────────────────
        for ev in NEW_EVENTS:
            exists = conn.execute(
                text("SELECT COUNT(*) FROM shock_events WHERE name=:name"), {"name": ev["name"]}
            ).scalar()
            if not exists:
                conn.execute(
                    text("""
                    INSERT INTO shock_events
                        (name, start, end, type, severity, source, region, description)
                    VALUES
                        (:name, :start, :end, :type, :severity, :source, :region, :description)
                """),
                    ev,
                )
                print(f"  Added: {ev['name']}")
            else:
                print(f"  Already present: {ev['name']}")

        # ── Final state ───────────────────────────────────────────────────────
        print("\n=== Final shock_events catalog ===")
        for row in conn.execute(
            text(
                "SELECT id, name, start, end, type, severity FROM shock_events ORDER BY start NULLS LAST"
            )
        ).fetchall():
            end_str = row[3] if row[3] else "ongoing"
            print(
                f"  [{row[0]}] {row[1][:50]:50s} {row[2]} -> {end_str}  type={row[4]}  sev={row[5]}"
            )

        count = conn.execute(text("SELECT COUNT(*) FROM rejected_events")).scalar()
        print(f"\nrejected_events: {count} entries")


if __name__ == "__main__":
    run()
