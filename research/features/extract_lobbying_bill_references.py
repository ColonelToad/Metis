"""
Extracts bill references (H.R./S./H.Res./S.Res. + number) out of
lobbying_activities descriptions, resolves the "See TRA"-style cross-reference
pattern first, derives the correct Congress number from the filing year (bill
numbers reset every Congress -- '(year - 1789) // 2 + 1'), and saves the
result as lobbying_bill_references, keyed to join against congress_bills.

v1, deliberately kept simple: this is a downstream processing step over
already-ingested lobbying_activities/lobbying_filings, not a new API call --
nothing here depends on lda.gov's API shape, so it's insulated from the kind
of API changes we're already expecting given the ongoing Senate->LDA.gov
migration. If the API changes again, this script is unaffected; only
ingest_lobbying_disclosures.py would need touching.

Congress-from-year is a strong proxy, not a logical guarantee -- a filing can
reference older legislation in retrospective discussion. Expected to be rare
relative to filings discussing live legislation, not treated as airtight.

Run from C:\\Users\\legot\\Metis:
    python research/features/extract_lobbying_bill_references.py
"""

import os
import re
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DB_URL = os.getenv("DB_URL", "sqlite:///data/metis.db")
engine = create_engine(DB_URL)

ISSUE_CODES = ["ENG", "FUE", "UTI", "ENV", "CAW", "MAR", "RRR"]

BILL_PATTERN = (
    r"\b(H\.?J\.?\s*Res\.?\s*\d+|S\.?J\.?\s*Res\.?\s*\d+|"
    r"H\.?Con\.?\s*Res\.?\s*\d+|S\.?Con\.?\s*Res\.?\s*\d+|"
    r"H\.?Res\.?\s*\d+|S\.?Res\.?\s*\d+|"
    r"H\.?R\.?\s*\d+|S\.?\s*\d+)\b"
)


def year_to_congress(year: int) -> int:
    """Bill numbers reset at the start of every Congress (every 2 years).
    2001 -> 107, 2023 -> 118 -- matches both real examples found manually."""
    return (int(year) - 1789) // 2 + 1


def normalize_bill_type(raw: str) -> str:
    """Normalize free-text mention to a short code, ignoring the trailing
    bill number entirely -- only classify the type."""
    clean = re.sub(r"[\.\s]", "", raw.upper())
    if clean.startswith("HCONRES"):
        return "HCONRES"
    if clean.startswith("SCONRES"):
        return "SCONRES"
    if clean.startswith("HJRES"):
        return "HJRES"
    if clean.startswith("SJRES"):
        return "SJRES"
    if clean.startswith("HRES"):
        return "HRES"
    if clean.startswith("SRES"):
        return "SRES"
    if clean.startswith("HR"):
        return "HR"
    if clean.startswith("S"):
        return "S"
    return clean


def resolve_cross_references(df: pd.DataFrame) -> pd.DataFrame:
    """'See TRA' rows point at a sibling row (same filing_uuid, that issue
    code) that has the actual substantive text -- resolve before extracting
    bill numbers, or these rows contribute nothing."""
    substantive = df[~df["description"].fillna("").str.startswith("See ", na=False)]
    lookup = (
        substantive.groupby(["filing_uuid", "general_issue_code"])["description"]
        .apply(lambda x: " | ".join(str(v) for v in x if pd.notna(v)))
        .to_dict()
    )

    def resolve(row):
        desc = str(row["description"]).strip()
        if not desc.startswith("See "):
            return desc
        target_codes = re.findall(r"\b[A-Z]{3}\b", desc)
        resolved = [
            lookup[(row["filing_uuid"], c)]
            for c in target_codes
            if (row["filing_uuid"], c) in lookup and lookup[(row["filing_uuid"], c)]
        ]
        return " | ".join(resolved) if resolved else desc

    df = df.copy()
    df["resolved_description"] = df.apply(resolve, axis=1)
    return df


def main():
    # Confirm congress_bills' real column names before building a join against
    # assumed ones -- the assumed names (congress, bill_type, bill_number,
    # title) came from a sample row seen much earlier in this project, never
    # from an actual schema check in this pass.
    cb_columns = pd.read_sql("SELECT * FROM congress_bills LIMIT 0", engine).columns.tolist()
    print(f"congress_bills real columns: {cb_columns}")
    required = ["congress", "bill_type", "bill_number"]
    missing = [c for c in required if c not in cb_columns]
    if missing:
        print(
            f"\nSTOP: assumed column(s) {missing} not found in congress_bills. "
            f"Real columns are printed above -- update the JOIN at the bottom of "
            f"this script to match before trusting any output below."
        )
        return 0

    activities = pd.read_sql("SELECT * FROM lobbying_activities", engine)
    filings = pd.read_sql("SELECT filing_uuid, filing_year FROM lobbying_filings", engine)

    df = activities.merge(filings, on="filing_uuid", how="left")
    df = df[df["general_issue_code"].isin(ISSUE_CODES)].copy()
    print(f"On-topic activity rows: {len(df)}")

    df = resolve_cross_references(df)

    df["bill_matches"] = df["resolved_description"].str.findall(BILL_PATTERN, flags=re.IGNORECASE)
    df = df[df["bill_matches"].apply(len) > 0].copy()
    print(f"Activities with at least one bill reference: {len(df)}")

    # Confirm the real target convention rather than assume it
    real_bill_types = pd.read_sql("SELECT DISTINCT bill_type FROM congress_bills", engine)[
        "bill_type"
    ].tolist()
    print(f"congress_bills.bill_type real distinct values: {real_bill_types}")

    rows = []
    for _, row in df.iterrows():
        congress = year_to_congress(row["filing_year"]) if pd.notna(row["filing_year"]) else None
        for match in row["bill_matches"]:
            clean = re.sub(r"[\.\s]", "", match.upper())
            bill_type = normalize_bill_type(match)
            bill_number = re.sub(
                r"\D",
                "",
                clean.replace("HRES", "").replace("SRES", "").replace("HR", "").replace("S", ""),
            )
            if bill_type not in real_bill_types:
                print(
                    f"  WARNING: normalized type '{bill_type}' not in congress_bills' real "
                    f"values -- check normalize_bill_type() mapping, e.g. from raw '{match}'"
                )
            rows.append(
                {
                    "filing_uuid": row["filing_uuid"],
                    "congress_number": congress,
                    "bill_type": bill_type,
                    "bill_number": bill_number,
                    "source_issue_code": row["general_issue_code"],
                    "raw_match": match,
                }
            )

    refs_df = pd.DataFrame(rows).drop_duplicates()
    print(f"\nTotal bill references extracted: {len(refs_df)}")

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS lobbying_bill_references (
                filing_uuid TEXT,
                congress_number INTEGER,
                bill_type TEXT,
                bill_number TEXT,
                source_issue_code TEXT,
                raw_match TEXT
            )
        """))
        conn.execute(text("DELETE FROM lobbying_bill_references"))  # v1: full rebuild each run

    refs_df.to_sql("lobbying_bill_references", engine, if_exists="append", index=False)
    print(f"Saved to lobbying_bill_references")

    # Quick join-test: does this actually connect to congress_bills, or just
    # look plausible? Real validation, not just producing output.
    joined = pd.read_sql(
        """
        SELECT lbr.filing_uuid, lbr.congress_number, lbr.bill_type, lbr.bill_number,
               cb.title
        FROM lobbying_bill_references lbr
        JOIN congress_bills cb
          ON lbr.congress_number = cb.congress
         AND lbr.bill_type = cb.bill_type
         AND lbr.bill_number = cb.bill_number
    """,
        engine,
    )
    print(
        f"\nJoin test: {len(joined)}/{len(refs_df)} extracted references "
        f"({len(joined)/max(len(refs_df),1)*100:.1f}%) actually matched a row in congress_bills"
    )
    if not joined.empty:
        print("Sample matches:")
        print(joined.head(10).to_string())

    return len(refs_df)


if __name__ == "__main__":
    main()
