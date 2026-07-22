"""
Parser for GOT-OCR (format=True) LaTeX table output -- confirmed against three
real vision-tier extractions (20003185, 20003367, 20003708), all Ashford 2015
filings. Distinct from TRANSACTION_RE, which is built for flat native/OCR text
and cannot match this format at all (different date syntax, cell-delimited
rows rather than a text stream).

Two confirmed, specific gaps in the underlying vision extraction itself
(not this parser's problem to solve, but worth tracking):
  - Dates render as '\\(D / D / YYYY\\)' -- single-digit day/month, spaced
    slashes, LaTeX math-mode wrapper. Handled below.
  - The Amount column is present in the header row across all three samples
    but absent from every actual data row. This parser does NOT require an
    amount to consider a row parsed -- it flags amount_missing=True instead,
    since asset/ticker/type/date are independently valuable and the current
    all-or-nothing regex was silently discarding rows that were 80% correct.
"""
import re

LATEX_DATE_RE = re.compile(r'\\?\(?\s*(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})\s*\\?\)?')
TICKER_RE = re.compile(r'\(([A-Z][A-Z0-9.]{0,6})\)\s*$')
MULTIROW_RE = re.compile(r'\\multirow\[?\w?\]?\{?\d*\}?\{?\*?\}?\{?\s*([A-Z]{0,3})\s*\}?')
# Metadata-only rows (FILING STATUS / SUBHOLDING OF / DESCRIPTION) sometimes
# render as plain &-delimited cells rather than \multicolumn{...} -- confirmed
# in real output for two of three sample documents. Those plain-cell versions
# pass the '&' in row check and were being picked up by the asset-name
# fallback as fake transactions with every other field None. Real transaction
# rows never start with one of these labels, so this is a safe, targeted skip.
METADATA_ROW_RE = re.compile(r'(filing status|subholding of|description)\s*:', re.IGNORECASE)
# Type letter can appear bare ('S') or LaTeX-math-wrapped ('\(S\)') -- confirmed
# both occur for the SAME document across different runs, not just across
# documents. Match content, not exact-equality against a raw cell string.
TYPE_RE = re.compile(r'^\\?\(?\s*([PSE])\s*\\?\)?$')
# Amount confirmed present in the real format '\(\$ 15,001-\$ 50,000\)'.
# Confirmed via direct byte-level debugging: the source text has a literal
# backslash character immediately before each '$' (LaTeX's escaped-dollar
# syntax), which the previous version didn't account for -- '\$' in a regex
# pattern matches the '$' character itself, it does not consume a preceding
# backslash *in the text being searched*. That silently broke the match on
# the second number every time, since nothing in the old pattern could step
# over that stray backslash between the dash and the second dollar sign.
AMOUNT_RE = re.compile(r'\\?\$\s*([\d,]+)\s*-\s*\\?\$?\s*([\d,]+)')


def normalize_date(raw: str) -> str:
    """'\\(7 / 2 / 2015\\)' -> '07/02/2015'. Returns raw unmodified if no match."""
    m = LATEX_DATE_RE.search(raw)
    if not m:
        return raw.strip()
    month, day, year = m.groups()
    return f"{int(month):02d}/{int(day):02d}/{year}"


def parse_latex_transaction_table(raw_text: str, filing_id: str) -> list:
    """Parse GOT-OCR LaTeX table output into transaction dicts."""
    results = []

    # Split into logical rows on \hline, drop the header row and anything
    # before the first real \hline-delimited data row.
    rows = re.split(r'\\hline', raw_text)

    for row in rows:
        row = row.strip()
        if not row or 'Owner' in row and 'Asset' in row:  # header row
            continue
        if '&' not in row:
            continue

        cells = [c.strip() for c in row.split('&')]
        if len(cells) < 4:
            continue  # not a real transaction row (e.g. a metadata-only fragment)
        if any(METADATA_ROW_RE.search(c) for c in cells):
            continue  # FILING STATUS/SUBHOLDING OF/DESCRIPTION row, not a transaction

        # Owner cell may use \multirow{...}{SP}, be blank, or contain the
        # asset name directly if owner was blank in the source (self-owned).
        owner_cell = cells[0]
        multirow_match = MULTIROW_RE.search(owner_cell)
        owner = multirow_match.group(1) if multirow_match and multirow_match.group(1) else None

        # Find which cell holds the asset+ticker: the one matching TICKER_RE,
        # or the first substantial cell if no ticker present (e.g. bonds).
        asset_cell = None
        ticker = None
        for c in cells:
            tm = TICKER_RE.search(c)
            if tm:
                ticker = tm.group(1)
                asset_cell = TICKER_RE.sub('', c).strip()
                break
        if asset_cell is None:
            # fallback: longest non-date, non-single-letter cell
            candidates = [c for c in cells if len(c) > 5 and not LATEX_DATE_RE.search(c)]
            asset_cell = candidates[0] if candidates else None

        # Transaction type: content-based search across all cells, tolerant of
        # both bare 'S' and LaTeX-math-wrapped '\(S\)' -- confirmed the SAME
        # document produces both across different runs, and confirmed the
        # column is sometimes entirely absent. Nullable, not required --
        # discarding a fully-extracted row for a missing type letter was
        # the exact all-or-nothing mistake already fixed for amount.
        txn_type = None
        for c in cells:
            tm = TYPE_RE.match(c.strip())
            if tm:
                txn_type = tm.group(1)
                break

        # Dates: cells matching the date pattern, in order of appearance
        date_cells = [c for c in cells if LATEX_DATE_RE.search(c)]
        txn_date = normalize_date(date_cells[0]) if len(date_cells) >= 1 else None
        notif_date = normalize_date(date_cells[1]) if len(date_cells) >= 2 else None

        # Amount: now confirmed present in some runs in the format
        # '\(\$ 15,001-\$ 50,000\)'. Actually parse it when present rather
        # than only flagging presence.
        amount_low, amount_high, raw_amount_cell = None, None, None
        for c in cells:
            am = AMOUNT_RE.search(c)
            if am:
                amount_low = float(am.group(1).replace(',', ''))
                amount_high = float(am.group(2).replace(',', ''))
                raw_amount_cell = c
                break

        if not asset_cell:
            continue  # need at minimum an asset to call this a transaction row

        results.append({
            'filing_id': filing_id,
            'owner': owner,
            'asset_description': asset_cell,
            'ticker': ticker,
            'transaction_type': txn_type,
            'transaction_date': txn_date,
            'notification_date': notif_date,
            'amount_low': amount_low,
            'amount_high': amount_high,
            'amount_missing': amount_low is None,
            'raw_amount_cell': raw_amount_cell,
        })

    return results


if __name__ == "__main__":
    # Quick local test harness for parsing a single GOT-OCR LaTeX table file.
    import sys
    if len(sys.argv) != 3:
        print("Usage: python parse_vision_latex.py <input_file> <filing_id>")
        sys.exit(1)

    input_file = sys.argv[1]
    filing_id = sys.argv[2]

    with open(input_file, 'r', encoding='utf-8') as f:
        raw_text = f.read()

    transactions = parse_latex_transaction_table(raw_text, filing_id)
    for txn in transactions:
        print(txn)