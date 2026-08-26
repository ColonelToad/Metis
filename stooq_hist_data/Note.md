Historical data as of 26 Jul 2026, 02:43 CEST

Role (Aug 2026 — data-control framing):Offline oracle / dispute arbiter — Stooq made bulk programmatic pulls harder, so this
snapshot is durable. Use it as (1) ticker-expansion seeder: bulk-load new
infra names into `stock_prices` instantly without yfinance rate limits,
then keep current via the scheduled ingester; (2) second independent voice
beside Yahoo + CME direct settlements whenever a price looks wrong; (3) NG
continuous contract `NG.US` as third opinion on rolls. `d_macro_txt.zip`
holds per-country macro series (CPI/GDP/PMI/rates) — potentially EU/Asia
macro for the European leg. Keep zips as-is (already compressed); ingest
on demand. Planned helper: `stooq_seeder.py` triggered at ticker-expansion
time.