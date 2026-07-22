"""
House PTR PDF Parser (Stage 2 of 2)

Reads house_ptr_index (built by ingest_house_ptr_index.py), fetches each PDF,
extracts transaction-level detail, and saves to house_ptr_trades.
"""
import os
import re
import sys
import tempfile
from pathlib import Path
from io import BytesIO
import pandas as pd
import requests
import pdfplumber
import ocrmypdf
from dotenv import load_dotenv
from sqlalchemy import create_engine
import torch
from transformers import AutoProcessor, AutoModelForImageTextToText

# --- 1. SET UP LOCAL CACHE ---
# This creates a 'models' folder in your current working directory
LOCAL_MODEL_DIR = os.path.join(os.getcwd(), "hf_models")
os.makedirs(LOCAL_MODEL_DIR, exist_ok=True)

# --- 2. GLOBALLY LOAD THE MODEL (Using Cache) ---
print(f"Loading GOT-OCR 2.0 from/to local cache at: {LOCAL_MODEL_DIR} ...")
DEVICE = "cpu"

# The cache_dir parameter ensures it downloads here once, and loads from here forever after
PROCESSOR = AutoProcessor.from_pretrained(
    "stepfun-ai/GOT-OCR-2.0-hf", 
    cache_dir=LOCAL_MODEL_DIR
)
MODEL = AutoModelForImageTextToText.from_pretrained(
    "stepfun-ai/GOT-OCR-2.0-hf", 
    device_map=DEVICE, 
    cache_dir=LOCAL_MODEL_DIR
)
print("Vision model loaded successfully.")

sys.path.append(str(Path(__file__).resolve().parents[2]))
from research.common import runtime_config as rc

load_dotenv()
DB_URL = rc.get_db_url()

# Regex pattern for transactions
TRANSACTION_RE = re.compile(
    r'(?:(?P<owner>DC|SP|JT)\s+)?'
    r'(?P<asset>.+?)'
    r'(?:\s*\((?P<ticker>[A-Z][A-Z0-9.]{0,6})\))?\s+'
    r'(?P<type>[PSE])\s+'
    r'(?P<txn_date>\d{2}/\d{2}/\d{4})\s+'
    r'(?P<notif_date>\d{2}/\d{2}/\d{4})\s+'
    r'\$(?P<amt_low>[\d,]+)\s*-\s*\$?(?P<amt_high>[\d,]+)',
    re.DOTALL
)

FILING_STATUS_RE = re.compile(r'filing status:\s*(.+?)(?:\n|$)', re.IGNORECASE)
SUBHOLDING_RE = re.compile(r'subholding of:\s*(.+?)(?:\n|$)', re.IGNORECASE)
DESCRIPTION_RE = re.compile(r'description:\s*(.+?)(?:\n\n|\nSP |\nDC |\nJT |$)', re.IGNORECASE | re.DOTALL)


def extract_native(pdf_bytes: bytes) -> str:
    """Extract embedded text directly using pdfplumber."""
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        return "".join((p.extract_text() or "") for p in pdf.pages)


def extract_via_ocr(pdf_bytes: bytes) -> str:
    """Run ocrmypdf natively in Linux/WSL using unpaper (clean=True) and deskew."""
    with tempfile.NamedTemporaryFile(suffix=".pdf") as in_f, \
         tempfile.NamedTemporaryFile(suffix=".pdf") as out_f:
        
        in_f.write(pdf_bytes)
        in_f.flush()
        
        try:
            # clean=True engages 'unpaper' to clean borders and noise
            ocrmypdf.ocr(
                in_f.name, 
                out_f.name, 
                deskew=True, 
                clean=True, 
                force_ocr=True, 
                progress_bar=False
            )
            with open(out_f.name, "rb") as f:
                return extract_native(f.read())
        except Exception as e:
            print(f"    ocrmypdf failed: {e}")
            return ""

def extract_via_vision(pdf_bytes: bytes) -> str:
    """Tier 3 Fallback: Use GOT-OCR 2.0 to reconstruct tables in Markdown."""
    ocr_results = []
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                # Convert PDF page to an image
                img = page.to_image(resolution=400).original
                
                # Format=True asks the model to output structured Markdown/tables
                inputs = PROCESSOR(img, return_tensors="pt", format=True).to(DEVICE)
                
                generate_ids = MODEL.generate(
                    **inputs,
                    do_sample=False,
                    tokenizer=PROCESSOR.tokenizer,
                    stop_strings="<|im_end|>",
                    max_new_tokens=4096,
                )
                
                page_text = PROCESSOR.decode(
                    generate_ids[0, inputs["input_ids"].shape[1]:], 
                    skip_special_tokens=True
                )
                ocr_results.append(page_text)
                
        return "\n\n".join(ocr_results)
    except Exception as e:
        print(f"    GOT-OCR 2.0 failed: {e}")
        return ""

def parse_transactions(raw_text: str, filing_id: str) -> list:
    """Parse transaction rows out of extracted text. Returns list of dicts."""
    results = []
    matches = list(TRANSACTION_RE.finditer(raw_text))
    if not matches:
        return results

    for i, m in enumerate(matches):
        span_start = m.end()
        span_end = matches[i + 1].start() if i + 1 < len(matches) else len(raw_text)
        metadata_block = raw_text[span_start:span_end]

        filing_status = FILING_STATUS_RE.search(metadata_block)
        subholding = SUBHOLDING_RE.search(metadata_block)
        description = DESCRIPTION_RE.search(metadata_block)

        results.append({
            'filing_id': filing_id,
            'owner': m.group('owner'),
            'asset_description': m.group('asset').strip(),
            'ticker': m.group('ticker'),
            'transaction_type': m.group('type'),
            'transaction_date': m.group('txn_date'),
            'notification_date': m.group('notif_date'),
            'amount_low': float(m.group('amt_low').replace(',', '')),
            'amount_high': float(m.group('amt_high').replace(',', '')),
            'filing_status': filing_status.group(1).strip() if filing_status else None,
            'subholding_of': subholding.group(1).strip() if subholding else None,
            'description': description.group(1).strip() if description else None,
        })

    return results

def parse_vision_latex(raw_text: str, filing_id: str) -> list:
    """Dedicated parser for GOT-OCR's LaTeX format output."""
    results = []
    lines = raw_text.split('\n')
    
    for line in lines:
        # Skip lines that aren't table rows or are table headers
        if '&' not in line or 'ID & Owner' in line or 'Transaction Date' in line:
            continue
            
        # Clean the row and split by the LaTeX column delimiter
        clean_line = line.replace('\\\\', '').strip()
        cols = [c.strip() for c in clean_line.split('&')]
        
        # We need at least the 5 base columns (Owner, Asset, Type, Txn Date, Notif Date)
        if len(cols) >= 5:
            owner_raw = cols[0]
            asset_raw = cols[1]
            type_raw = cols[2].replace('\\', '').strip() # Clean stray slashes
            txn_date_raw = cols[3]
            notif_date_raw = cols[4]
            
            # Skip rows where it hallucinated metadata into the transaction type column
            if type_raw not in ['P', 'S', 'E'] and type_raw != '':
                continue
                
            # 1. Clean Owner (Extract SP, DC, JT from \multirow[t]{2}{*}{ SP })
            owner_match = re.search(r'(SP|DC|JT)', owner_raw)
            owner = owner_match.group(1) if owner_match else None
            
            # 2. Clean Dates (Strip spaces, slashes, and LaTeX math parentheses)
            # Turns "\(05 / 5 / 2015\)" into "05/5/2015"
            txn_date = re.sub(r'[\\\(\)\s]', '', txn_date_raw)
            notif_date = re.sub(r'[\\\(\)\s]', '', notif_date_raw)
            
            # 3. Clean Asset & Ticker
            ticker_match = re.search(r'\(([A-Z0-9.]+)\)', asset_raw)
            ticker = ticker_match.group(1) if ticker_match else None
            asset = re.sub(r'\([A-Z0-9.]+\)', '', asset_raw).strip()

            # 4. Handle Amounts (Check if the resolution bump actually found a 6th column)
            amount_low = 0.0
            amount_high = 0.0
            if len(cols) >= 6:
                amt_raw = cols[5]
                amt_match = re.search(r'\$?([\d,]+)\s*-\s*\$?([\d,]+)', amt_raw)
                if amt_match:
                    amount_low = float(amt_match.group(1).replace(',', ''))
                    amount_high = float(amt_match.group(2).replace(',', ''))

            # Only append if we successfully parsed a transaction type
            if type_raw in ['P', 'S', 'E']:
                results.append({
                    'filing_id': filing_id,
                    'owner': owner,
                    'asset_description': asset,
                    'ticker': ticker,
                    'transaction_type': type_raw,
                    'transaction_date': txn_date,
                    'notification_date': notif_date,
                    'amount_low': amount_low,
                    'amount_high': amount_high,
                    'filing_status': None, # Deferred: Meta parsing requires multi-row lookahead
                    'subholding_of': None,
                    'description': None,
                })
                
    return results

def process_filing(row) -> tuple:
    """Fetch, extract, and parse one filing using a 3-tier cascade."""
    try:
        resp = requests.get(row['pdf_url'], timeout=30)
        resp.raise_for_status()
        pdf_bytes = resp.content
    except Exception as e:
        print(f"  {row['DocID']}: fetch error: {e}")
        return [], 'fetch_error', 0

    # TIER 1: Native embedded text
    native_text = extract_native(pdf_bytes)
    if len(native_text.strip()) > 20:
        txns = parse_transactions(native_text, row['DocID'])
        if txns:
            return txns, 'native', len(native_text)

    # TIER 2: Classic OCR Fallback via WSL ocrmypdf
    ocr_text = extract_via_ocr(pdf_bytes)
    if len(ocr_text.strip()) > 20:
        txns = parse_transactions(ocr_text, row['DocID'])
        if txns:
            return txns, 'ocr_classic', len(ocr_text)
            
    # TIER 3: Vision Model Fallback 
    print(f"  {row['DocID']}: Classic OCR failed to find tables. Trying Vision Model...")
    vision_text = extract_via_vision(pdf_bytes)
    
    if len(vision_text.strip()) > 20:
        # Use the dedicated LaTeX parser, NOT the native text regex
        txns = parse_vision_latex(vision_text, row['DocID'])
        
        # Always dump the vision output for now so you can check if the 400 DPI found the amounts
        debug_dir = "ocr_debug_dumps"
        os.makedirs(debug_dir, exist_ok=True)
        dump_path = os.path.join(debug_dir, f"{row['DocID']}_vision_dump.txt")
        with open(dump_path, "w", encoding="utf-8") as f:
            f.write(vision_text)
            
        if txns:
            return txns, 'ocr_vision', len(vision_text)

        print(f"    --> Dumped vision Markdown to {dump_path}")

    print(f"  {row['DocID']}: empty/failed after all 3 attempts")
    return [], 'empty_all', 0


def main():
    rc.log_mode("House PTR PDF Parser")
    if not rc.require_real_mode("House PTR PDF parsing"):
        return 0

    engine = create_engine(DB_URL)
    index_df = pd.read_sql("SELECT * FROM house_ptr_index", engine)
    print(f"Processing {len(index_df)} indexed filings...")

    all_transactions = []
    method_counts = {}
    for i, row in index_df.iterrows():
        if i % 100 == 0:
            print(f"  ...{i}/{len(index_df)}")
        txns, method, _ = process_filing(row)
        method_counts[method] = method_counts.get(method, 0) + 1
        for t in txns:
            t['extraction_method'] = method
        all_transactions.extend(txns)

    print(f"\nExtraction method breakdown: {method_counts}")
    print(f"Total transactions parsed: {len(all_transactions)}")

    if not all_transactions:
        print("No transactions parsed")
        return 0

    trades_df = pd.DataFrame(all_transactions)
    trades_df.to_sql('house_ptr_trades', engine, if_exists='replace', index=False)
    print(f"Saved {len(trades_df)} trade records to house_ptr_trades")
    return len(trades_df)


if __name__ == "__main__":
    main()