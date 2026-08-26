"""
GDELT Framing Pilot (N1) - empirical-first aggregate news-framing curves
for four pre-registered windows, to be LOOKED AT beside prices before any
feature design is frozen.

Data route: daily consolidated GKG files (gkg/YYYYMMDD.gkg.csv.zip,
V1-format: DATE,NUMARTS,COUNTS,THEMES,LOCATIONS,PERSONS,ORGANIZATIONS,TONE,
CAMEOEVENTIDS,SOURCES,SOURCEURLS with a header row). No key, no BigQuery.
Zips cached under data/cache/gdelt_gkg/.

Matching is type-aware:
  - theme terms  -> semicolon-list membership in the THEMES column
    (controlled vocabulary discovered empirically; see THEME_TERMS below)
  - entity terms -> substring in LOCATIONS|PERSONS|ORGANIZATIONS

Windows:
  iran_2025          Jun 01 - Jul 15 2025   Iran entity mentions
  repowereu_2022     Mar 08 - Jun 30 2022   REPowerEU org mention + EU gas themes
  election_2024      Oct 15 - Dec 15 2024   clean-energy vs fossil-fuel themes
  cpp_collapse_2016  Jan 01 - Mar 31 2016   Clean Power Plan mentions

Outputs (research/analysis/out/gdelt_pilot/): per-series CSVs + panel PNG.
"""

import io
import logging
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import requests

matplotlib.use("Agg")
import matplotlib.pyplot as plt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

OUT = Path(__file__).parent / "out" / "gdelt_pilot"
CACHE = Path("data/cache/gdelt_gkg")
OUT.mkdir(parents=True, exist_ok=True)
CACHE.mkdir(parents=True, exist_ok=True)

# Controlled-vocabulary terms (from THEMES), matched as exact tokens or
# prefixes; entity terms matched as substring over location/person/org text.
WINDOWS = [
    ("iran_2025", datetime(2025, 6, 1), datetime(2025, 7, 15), [("iran_entity", "entity", "IRAN")]),
    (
        "repowereu_2022",
        datetime(2022, 3, 8),
        datetime(2022, 6, 30),
        [
            ("repowereu_org", "entity", "REPOWEREU"),
            (
                "eu_gas_themes",
                "theme_any",
                ["ENV_NATURALGAS", "ECON_NATGASPRICE", "WB_1751_LIQUEFIED"],
            ),
        ],
    ),
    (
        "election_2024",
        datetime(2024, 10, 15),
        datetime(2024, 12, 15),
        [
            (
                "clean_energy_theme",
                "theme_any",
                [
                    "WB_525_RENEWABLE_ENERGY",
                    "ENV_SOLAR",
                    "WB_528_SOLAR_ENERGY",
                    "ENV_WINDPOWER",
                    "WB_529_WIND_ENERGY",
                ],
            ),
            ("fossil_theme", "theme_any", ["ENV_OIL", "ENV_COAL", "ENV_NATURALGAS"]),
            (
                "energy_price_theme",
                "theme_any",
                ["ECON_OILPRICE", "ECON_NATGASPRICE", "ECON_GASOLINEPRICE"],
            ),
        ],
    ),
    (
        "cpp_collapse_2016",
        datetime(2016, 1, 1),
        datetime(2016, 3, 31),
        [
            ("clean_power_plan", "entity", "CLEAN POWER PLAN"),
            ("climate_theme", "theme_prefix", "ENV_CLIMATECHANGE"),
        ],
    ),
]

IDX_DATE, IDX_THEMES, IDX_LOCS, IDX_PERSONS, IDX_ORGS, IDX_TONE = 0, 3, 4, 5, 6, 7


def daterange(d1, d2):
    d = d1
    while d <= d2:
        yield d
        d += timedelta(days=1)


def fetch_day(day: datetime, keys: list):
    """keys: [(result_key, kind, payload)]. Returns dict or None."""
    cache_path = CACHE / f"{day:%Y%m%d}.zip"
    if cache_path.exists():
        raw = cache_path.read_bytes()
    else:
        url = f"https://data.gdeltproject.org/gkg/{day:%Y%m%d}.gkg.csv.zip"
        for attempt in range(3):
            try:
                r = requests.get(url, timeout=180)
                break
            except requests.RequestException as e:
                if attempt == 2:
                    log.warning(f"{day:%Y%m%d}: download failed ({str(e)[:60]})")
                    return None
                time.sleep(5 * (attempt + 1))
        if r.status_code != 200:
            return None
        cache_path.write_bytes(r.content)
        raw = r.content

    z = zipfile.ZipFile(io.BytesIO(raw))
    lines = z.read(z.namelist()[0]).decode("utf-8", errors="replace").splitlines()
    rows = [l.split("\t") for l in lines[1:]]  # first line is a header
    rows = [f for f in rows if len(f) > IDX_TONE]
    if not rows:
        return None

    # V1 GKG TONE field = "tone,pos,neg,polarity,activity,ref" (comma-packed)
    tones = np.array(
        [
            float(f[IDX_TONE].split(",")[0]) if _is_float(f[IDX_TONE].split(",")[0]) else np.nan
            for f in rows
        ]
    )
    themes_split = [set(f[IDX_THEMES].split(";")) for f in rows]
    entity_text = [f"{f[IDX_LOCS]} {f[IDX_PERSONS]} {f[IDX_ORGS]}".upper() for f in rows]

    matches = {}
    for key, kind, payload in keys:
        if kind == "theme_any":
            hit = [i for i, ts in enumerate(themes_split) if ts & set(payload)]
        elif kind == "theme_prefix":
            hit = [i for i, ts in enumerate(themes_split) if any(t.startswith(payload) for t in ts)]
        else:  # entity substring
            hit = [i for i, txt in enumerate(entity_text) if payload in txt]
        tone = float(np.nanmean(tones[hit])) if hit else None
        matches[key] = {"n": len(hit), "tone": tone, "share": len(hit) / len(rows)}
    return {"date": day.date().isoformat(), "total": len(rows), "matches": matches}


def _is_float(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def main():
    day_keys = {}
    for wname, d1, d2, terms in WINDOWS:
        for d in daterange(d1, d2):
            day_keys.setdefault(d, []).extend(
                (f"{wname}:{slug}", kind, payload) for slug, kind, payload in terms
            )

    all_days = sorted(day_keys)
    log.info(f"Day-files: {len(all_days)} (cached ones are free)")

    results, totals = {}, {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(fetch_day, d, day_keys[d]) for d in all_days]
        for i, fut in enumerate(as_completed(futs), 1):
            res = fut.result()
            if res:
                totals[res["date"]] = res["total"]
                for key, m in res["matches"].items():
                    results.setdefault(key, {})[res["date"]] = (m["n"], m["tone"], m["share"])
            if i % 25 == 0:
                log.info(f"  {i}/{len(all_days)} ({time.time()-t0:.0f}s)")

    import pickle

    with open(OUT / "pilot_cache.pkl", "wb") as f:
        pickle.dump({"totals": totals, "results": results}, f)

    fig, axes = plt.subplots(len(WINDOWS), 1, figsize=(12, 3.2 * len(WINDOWS)))
    summary = []
    for ax, (wname, _, _, terms) in zip(np.atleast_1d(axes), WINDOWS):
        for slug, _, _ in terms:
            key = f"{wname}:{slug}"
            series = results.get(key, {})
            if not series:
                summary.append(f"{key:34s} NO DATA")
                continue
            s = pd.DataFrame(
                [(d, *v) for d, v in sorted(series.items())],
                columns=["date", "n_matched", "mean_tone", "share"],
            )
            s.to_csv(OUT / f"{wname}_{slug}.csv", index=False)
            x = pd.to_datetime(s["date"])
            ax.plot(x, s["share"], label=slug)
            ax.set_title(wname)
            ax.set_ylabel("share of articles")
            ax.grid(alpha=0.3)
            ax.legend(loc="upper left")
            ax2 = ax.twinx()
            ax2.plot(x, s["mean_tone"], linestyle="--", alpha=0.35, color="gray")
            ax2.set_ylabel("mean tone", alpha=0.5)
            peak = s.loc[s["n_matched"].idxmax()]
            summary.append(
                f"{key:26s} days={len(s):3d} peak={peak['date']} "
                f"n={int(peak['n_matched']):6d} share={peak['share']*100:6.2f}% "
                f"tone_mean={s['mean_tone'].mean():+.2f}"
            )
    fig.tight_layout()
    fig.savefig(OUT / "framing_panel.png", dpi=130)
    print("\n".join(summary))
    log.info(f"Wrote outputs to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
