"""
Ticker lineage table -- documents cases where a company's ticker symbol
changed, or where the same ticker symbol was reused for a genuinely
different security, so these discontinuities are explicit and queryable
rather than silent gaps discovered painfully later.

Two distinct failure modes this captures, deliberately kept separate via
same_symbol_discontinuity:

  - Simple rename/merger (old_ticker != new_ticker): the underlying business
    entity has real continuity, it just trades under a new symbol. A naive
    "just query the old ticker" approach fails loudly (404/delisted), which
    is at least visible -- exactly what happened with CHK -> EXE this session.

  - Same-symbol discontinuity (old_ticker == new_ticker): the SYMBOL never
    changed, but the underlying instrument did -- e.g. a bankruptcy
    reorganization that cancels old equity and issues genuinely new shares
    under the same ticker. This is the more dangerous case, because a naive
    continuous pull shows no error at all -- just a real, correct-looking
    price series with a massive discontinuity that isn't a market crash,
    it's two different securities sharing four letters.

Run from C:\\Users\\legot\\Metis:
    python research/data_ingest/build_ticker_lineage.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.append(str(Path(__file__).resolve().parents[2]))
from research.common import runtime_config as rc

load_dotenv()
DB_URL = rc.get_db_url()

# Hand-maintained. At ~18 tickers this is the right-sized version of what
# CUSIP/ISIN/FIGI solve at institutional scale -- add a row here whenever a
# lineage event is discovered, rather than letting it become undocumented
# tribal knowledge the next time it happens.
LINEAGE_EVENTS = [
    {
        "old_ticker": "CHK",
        "new_ticker": "CHK",
        "change_date": "2021-02-09",
        "change_type": "bankruptcy_reorganization",
        "same_symbol_discontinuity": 1,
        "note": (
            "Chesapeake filed Chapter 11 on 2020-06-28. Plan effective 2021-02-09: "
            "old preferred/common equity CANCELLED, ~$7.8B debt equitized, "
            "~97.9M new common shares issued and listed under the same 'CHK' "
            "ticker, trading resumed 2021-02-10. Pre- and post-emergence CHK "
            "are NOT the same instrument despite the identical symbol -- "
            "pre-2020 shareholders were wiped out entirely."
        ),
        "source_url": "https://www.sec.gov/Archives/edgar/data/895126/000089512621000035/form8-axemergence.htm",
    },
    {
        "old_ticker": "CHK",
        "new_ticker": "EXE",
        "change_date": "2024-10-02",
        "change_type": "merger_rename",
        "same_symbol_discontinuity": 0,
        "note": (
            "Chesapeake completed its merger with Southwestern Energy (SWN) "
            "on 2024-10-01; combined company rebranded Expand Energy, began "
            "trading as 'EXE' on 2024-10-02. More genuine business continuity "
            "than the 2021 event -- this is a ticker/name change plus "
            "asset-base expansion (absorbed Southwestern), not an equity wipeout."
        ),
        "source_url": "https://www.sec.gov/Archives/edgar/data/7332/000110465924104962/tm2425085d1_ex99-1.htm",
    },
]


def main():
    engine = create_engine(DB_URL)

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ticker_lineage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                old_ticker TEXT NOT NULL,
                new_ticker TEXT NOT NULL,
                change_date TEXT NOT NULL,
                change_type TEXT NOT NULL,
                same_symbol_discontinuity INTEGER NOT NULL DEFAULT 0,
                note TEXT,
                source_url TEXT
            )
        """))

        for event in LINEAGE_EVENTS:
            existing = conn.execute(
                text(
                    "SELECT COUNT(*) FROM ticker_lineage WHERE old_ticker=:old_ticker "
                    "AND new_ticker=:new_ticker AND change_date=:change_date"
                ),
                event,
            ).scalar()
            if existing:
                print(
                    f"  Already present: {event['old_ticker']} -> {event['new_ticker']} "
                    f"({event['change_date']}), skipping"
                )
                continue
            conn.execute(
                text("""
                INSERT INTO ticker_lineage
                    (old_ticker, new_ticker, change_date, change_type,
                     same_symbol_discontinuity, note, source_url)
                VALUES
                    (:old_ticker, :new_ticker, :change_date, :change_type,
                     :same_symbol_discontinuity, :note, :source_url)
            """),
                event,
            )
            print(
                f"  Added: {event['old_ticker']} -> {event['new_ticker']} "
                f"({event['change_date']}, {event['change_type']})"
            )

    print("\nticker_lineage table ready.")


if __name__ == "__main__":
    main()
