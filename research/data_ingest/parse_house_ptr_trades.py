"""
House PTR PDF Parser - Stage 2 (Spatial Table Extraction)

Reads house_ptr_index, fetches each PDF, extracts transaction-level detail 
using pdfplumber's spatial layout engine, and saves to house_ptr_trades.
Includes a debug mode to output raw row text.
"""
import os
import sys
from pathlib import Path
from io import BytesIO
import pandas as pd
import requests
import pdfplumber
from dotenv import load_dotenv
from sqlalchemy import create_engine
import re
import pytesseract

# --- SET UP DEBUG CACHE ---
DEBUG_DIR = os.path.join(os.getcwd(), "debug_filings")
os.makedirs(DEBUG_DIR, exist_ok=True)

sys.path.append(str(Path(__file__).resolve().parents[2]))
from research.common import runtime_config as rc

load_dotenv()
DB_URL = rc.get_db_url()

def extract_spatial_tables(pdf_bytes: bytes, filing_id: str) -> tuple:
    """
    Extracts text preserving exact visual spacing for debugging and parsing.
    Returns a list of parsed transaction dictionaries.
    """
    transactions = []
    debug_lines = [f"--- FILING ID: {filing_id} ---"]
    
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                debug_lines.append(f"\n[PAGE {page_num}]\n")
                
                # layout=True forces pdfplumber to use space characters to mimic
                # the exact visual X/Y coordinates of the text on the page.
                page_text = page.extract_text(layout=True)
                
                # --- MODIFIED BLOCK STARTS HERE ---
                if not page_text or not page_text.strip():
                    debug_lines.append("[No native text detected. Running in-memory Tesseract with Auto-Rotation...]\n")
                    
                    # Convert the pdfplumber page to a high-res PIL image
                    page_image = page.to_image(resolution=300).original
                    
                    # 1. Detect and Fix Rotation
                    try:
                        # image_to_osd returns a string containing orientation metadata
                        osd_output = pytesseract.image_to_osd(page_image)
                        angle_match = re.search(r'(?<=Rotate: )\d+', osd_output)
                        
                        if angle_match:
                            angle = int(angle_match.group(0))
                            if angle != 0:
                                debug_lines.append(f"[Auto-detect: Image rotated by {angle} degrees. Correcting...]\n")
                                # Tesseract's "Rotate: X" indicates the amount of counter-clockwise 
                                # rotation needed. PIL's rotate() rotates counter-clockwise.
                                # We use -angle (or 360-angle) to apply the correction properly. 
                                # expand=True prevents the corners from being cropped off.
                                page_image = page_image.rotate(-angle, expand=True)
                    except Exception as e:
                        debug_lines.append(f"[Auto-rotation check failed or skipped: {e}]\n")

                    # 2. Extract Text with Adjusted PSM
                    # --psm 4 assumes a single column of text of variable sizes, which is 
                    # generally better for horizontal rows with scattered spacing than PSM 6.
                    page_text = pytesseract.image_to_string(page_image, config='--psm 4')
                    
                    if not page_text or not page_text.strip():
                        debug_lines.append("Tesseract also found no text on this page.")
                        continue
                # --- MODIFIED BLOCK ENDS HERE ---
                
                debug_lines.append(page_text)
                
                # We can now parse this page_text line-by-line. 
                # (Parsing logic goes here once we confirm the layout structure)

    except Exception as e:
        debug_lines.append(f"PDF Parsing Failed: {e}")
        
    # Write the debug file so you can inspect the visual text output
    debug_path = os.path.join(DEBUG_DIR, f"{filing_id}_layout.txt")
    with open(debug_path, "w", encoding="utf-8") as f:
        f.write("\n".join(debug_lines))
        
    return transactions, 'spatial_layout', len(debug_lines)


def process_filing(row) -> tuple:
    """Fetch PDF and pass to the spatial extractor."""
    try:
        resp = requests.get(row['pdf_url'], timeout=30)
        resp.raise_for_status()
        pdf_bytes = resp.content
    except Exception as e:
        print(f"  {row['DocID']}: fetch error: {e}")
        return [], 'fetch_error', 0

    return extract_spatial_tables(pdf_bytes, row['DocID'])


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
        all_transactions.extend(txns)

    print(f"\nExtraction method breakdown: {method_counts}")
    print(f"Total transactions parsed: {len(all_transactions)}")
    print(f"Check the '{DEBUG_DIR}' directory to review the raw extracted rows.")

    if not all_transactions:
        print("No transactions parsed")
        return 0

    trades_df = pd.DataFrame(all_transactions)
    trades_df.to_sql('house_ptr_trades', engine, if_exists='replace', index=False)
    print(f"Saved {len(trades_df)} trade records to house_ptr_trades")
    return len(trades_df)

if __name__ == "__main__":
    main()