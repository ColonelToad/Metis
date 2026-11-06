# Data Source Issues Register

A running record of source-side changes, bans, and gaps between what an
ingester *reports* and what actually landed in the database. This is a
deliberate slow project: entries are logged when discovered, triaged later,
and closed only when the data is verified.

Rules:

- **A source ban is final for automation.** If a provider blocks this host
  (explicit 403, terms-of-use message, IP block), record it here and stop.
  Do not attempt alternate scraping paths, proxies, or browser tricks.
- Freshness (`max(date)` vs. publication lag) is the evidence that a source
  actually delivered. An ingester exiting 0 is not evidence.
- Record the observed value, the query/date, and the table, so the entry can
  be re-checked without re-deriving it.

Last updated: 2026-11-05

---

## Blocked / banned

### CME Group — settlements and daily bulletin
- **Status:** blocked; parked 2026-11-04.
- **Evidence:** `https://www.cmegroup.com/CmeWS/...` returns HTTP 403 with
  `"This IP address is blocked due to suspected web scraping activity ..."`.
  Playwright landing-page navigation fails with
  `Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR`.
- **Impact:** `cme_settlements` is frozen at 2026-08-21 (5 trading days:
  2026-08-17..2026-08-21). `CME Settlements (direct)` was removed from
  `DAILY_INGESTERS`; the module is kept but not scheduled.
- **Next step:** a licensed/authorized feed or a different network with
  permission. No scraping workaround will be attempted.

---

## Open

### `drought_conditions` — every row is 1970-01-01
- **Observed 2026-11-05:** 1,252 rows, `min(date)=1970-01-01
  00:00:00.020000`, `max(date)=1970-01-01 00:00:00.020231`. All 1,252 rows are
  before 2000.
- **Meaning:** the parser is turning a serial/epoch value into a sentinel
  date. The table contains no usable drought history even though the ingester
  reports success.
- **Impact:** any drought feature is meaningless until fixed and backfilled.

### `census_permits` — 12 rows, nine months stale
- **Observed 2026-11-05:** 12 rows, `2025-03-01 .. 2026-02-01`.
- **Note:** a separate `census_building_permits` table has 30 rows. The
  backfill config targets 10 years but the table holds under one.

### `maritime_ais` and `eia_jet_fuel` — tables exist, zero columns
- **Observed 2026-11-05:** `pragma table_info` returns no columns for either.
- **Meaning:** the ingesters have never successfully written a row; the
  tables were created empty by a schema step. Freshness cannot be measured
  (`fresh=None`, "no such table"/no column).
- **Impact:** AIS and jet-fuel features are absent, not merely stale.

### `cme_futures_daily` — Yahoo-derived, source identity unverified
- **Observed 2026-11-05:** 15,874 rows, `2016-03-08 .. 2026-10-30`.
- **Concern:** the settlements module describes the futures series as
  "Yahoo Finance-derived". After the CME block, this is the only futures
  price source; confirm it still matches an official settlement before
  trusting it for validation.

### EIA storage rewrite is destructive
- **File:** `research/data_ingest/ingest_eia.py`
- **Behavior:** `to_sql("eia_storage", if_exists="replace")` drops and
  recreates the table on every run. A partial API response would silently
  replace complete history with a short series.
- **Observed 2026-11-05:** 625 national rows through 2026-10-30 after the
  Thursday release (the prior run, on 11/4, correctly showed 10/23). The data
  is current; the write pattern is the risk.

### Ledger `row_count` is mostly zero
- **Observed 2026-11-04/05:** only `ingest_bls_ppi.main()` returns an int.
  Most ingesters return `None`, so `logs/ingest_ingesters.json` records
  `row_count: 0` even when rows were written (Weather showed 0 while its
  table was current).
- **Rule:** treat freshness as the success signal until each `main()` returns
  its write count.

### Mixed timestamp semantics across tables
- Local naive (`bls_ppi.timestamp`, `storm_events.timestamp`,
  `cme_settlements.trade_date`), UTC (`congress_bills.timestamp`,
  `state_bills.fetched_at`), and period-start dates (`eia_storage`,
  `census_permits`) coexist. Freshness and joins can be off by hours, and a
  monthly series is always "one period old" by construction.

### `lobbying_bill_references` extraction is non-atomic
- `DELETE` runs in one transaction and `to_sql(append)` in another
  (`research/features/extract_lobbying_bill_references.py`). A crash between
  them empties the table. A backup (`lobbying_bill_references_bak`, 4,622
  rows) exists before reruns.

### Fabricated history retained for audit
- `bls_ppi_synthetic_bak`: 7,560 fabricated rows from the old synthetic
  fallback. Never use for analysis.
- `grid_lmp_multi_iso_bak_20261104`: 433,593-row snapshot taken before the
  contaminated ISO rows were purged (see below).

### `grid_lmp_multi_iso` history gap 2026-10-07 .. 2026-10-24
- NYISO/ISO-NE rows before 2026-10-25 were purged as mislabeled CAISO data.
  CAISO history was kept. The current window (2026-10-25 onward) is real for
  all three ISOs. Backfill the gap only if a study needs it.

---

## Fixed (kept for the record)

### `grid_lmp_multi_iso` served CAISO data under NYISO/ISO-NE labels
- **Found 2026-11-04.** `ttl_cache` keyed only on the cache name, not the
  arguments, so after the CAISO fetch the NYISO and ISO-NE calls returned the
  cached CAISO frame. All 144,531 NYISO rows and 144,531 ISO-NE rows were
  byte-identical to CAISO, including CAISO node IDs
  (`TH_NP15_GEN-APND`, ...).
- **Also:** `get_lmp(date=start)` ignored `end`, so the "last 30 days"
  fallback fetched one day 30 days ago every run — a permanent 30-day lag.
- **Also:** the append failed on overlap and the row-by-row fallback counted
  ignored rows as inserted.
- **Fix 2026-11-04:** argument-keyed cache; explicit `end=`; incremental
  config + 14-day cap; staging table + `INSERT OR REPLACE`; ISO-NE limited to
  8 zones + internal hub (instead of ~1,200 nodes); empty result raises.
- **Verified 2026-11-05:** 84,234 rows across 10 days; CAISO 3 nodes, NYISO
  15 zones, ISO-NE 9 zones; zero duplicate keys.

### EIA weekly storage freshness threshold was too tight
- The newest published week is the prior Friday (10/23 on 11/4), so a
  10-day limit flagged normal Thursday-release lag. Raised to 14 days.

### BLS PPI synthetic fallback
- Old code wrote fabricated values on API failure. Replaced with four
  live-verified series and `BLSFetchError`; see commit `1375cab`.

---

## How to add an entry

Include: source, date observed, exact query/table, observed values, what it
means, impact, and whether it is blocked. If a provider has banned this host,
mark it **blocked** and stop — do not test workarounds.
