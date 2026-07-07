"""
FERC Data Ingestion for RAG Context - Structural Constraints Layer

Fetches FERC datasets related to natural gas infrastructure and market structure:
- Dataset 15: Entities to Vertical Assets (transmission, storage, distribution assets)
- Dataset 27: NEPA Schedule (pending infrastructure projects, timelines)

Stores in SQLite + LanceDB vector store for RAG retrieval (Layer 2: structural constraints).

Usage (standalone test with API key):
    FERC_API_KEY=your_key python research/data_ingest/ingest_ferc_datasets.py --dry-run

Usage (integrated in daily pipeline):
    from research.data_ingest.ingest_ferc_datasets import fetch_and_ingest_ferc_datasets
    await fetch_and_ingest_ferc_datasets()

Note: For regulatory decisions (orders, notices, dockets), see ingest_ferc_elibrary.py
"""
import os
import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import requests
import pandas as pd
from sqlalchemy import create_engine, text

# Setup logging
logging.basicConfig(level=logging.INFO, format="[FERC] %(message)s")
logger = logging.getLogger(__name__)

# Add parent directory to path
parent_dir = str(Path(__file__).parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from common import runtime_config as rc

FERC_API_BASE = "https://www.ferc.gov/api"
FERC_API_KEY = os.getenv("FERC_API_KEY")

# Natural gas and pipeline-related subjects to filter by
FERC_SUBJECTS = [
    "natural gas",
    "pipeline",
    "rate",
    "certificate",
    "lng",
    "liquefied natural gas",
    "transmission",
    "capacity",
    "infrastructure",
]

DB_URL = rc.get_db_url("sqlite:///data/metis.db")


def is_ng_relevant(title: str, subject: str = "") -> bool:
    """Check if order is relevant to natural gas trading"""
    text_blob = f"{title} {subject}".lower()
    return any(keyword in text_blob for keyword in FERC_SUBJECTS)


def fetch_ferc_orders(
    limit: int = 500,
    api_key: Optional[str] = None,
    dry_run: bool = False
) -> pd.DataFrame:
    """
    Fetch recent FERC orders from the public API.

    Args:
        limit: Maximum orders to fetch
        api_key: FERC API key (uses environment if not provided)
        dry_run: If True, don't make actual API call (log only)

    Returns:
        DataFrame with columns: docket_id, title, subject, issued_date,
                               summary, full_text_url, order_type, timestamp
    """
    api_key = api_key or FERC_API_KEY

    if dry_run:
        logger.info(f"DRY RUN: Would fetch {limit} FERC orders")
        return pd.DataFrame()

    if not rc.require_real_mode("FERC API"):
        logger.info("Skipping FERC fetch (not in REAL mode)")
        return pd.DataFrame()

    if not api_key:
        logger.warning("FERC_API_KEY not set - skipping FERC ingestion")
        return pd.DataFrame()

    logger.info(f"Fetching FERC orders (limit={limit})...")

    try:
        # FERC API v1 orders endpoint
        url = f"{FERC_API_BASE}/v1/orders"
        params = {
            "api_key": api_key,
            "limit": min(limit, 1000),  # API max
            "offset": 0,
            "sort": "date_issued",
            "order": "desc",
        }

        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Parse error: {e}")
        return pd.DataFrame()

    # Extract orders from response
    orders = data.get("data", []) if isinstance(data, dict) else []
    logger.info(f"API returned {len(orders)} orders")

    records: List[Dict[str, Any]] = []
    filtered_count = 0

    for order in orders:
        title = order.get("title", "")
        subject = order.get("subject", "")
        issued_date = order.get("date_issued")

        # Filter: only include NG-relevant subjects
        if not is_ng_relevant(title, subject):
            filtered_count += 1
            continue

        records.append({
            "docket_id": order.get("docket_id", ""),
            "title": title,
            "subject": subject,
            "issued_date": issued_date,
            "summary": order.get("summary", order.get("description", "")),
            "full_text_url": order.get("document_url") or order.get("url", ""),
            "order_type": order.get("type", "ORDER"),
            "timestamp": datetime.now(timezone.utc),
        })

    logger.info(f"Filtered to {len(records)} NG-relevant orders (excluded {filtered_count})")
    return pd.DataFrame(records)


def ingest_to_rag(df: pd.DataFrame, mock_mode: bool = False) -> int:
    """
    Convert FERC orders to RAG documents and embed them in LanceDB.

    Args:
        df: DataFrame with FERC orders
        mock_mode: If True, skip actual embedding (for testing)

    Returns:
        Number of documents ingested
    """
    if df.empty:
        logger.info("No documents to ingest")
        return 0

    try:
        from rag.vectorstore.lancedb_store import LanceVectorStore
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        logger.error(f"Missing RAG dependencies: {e}")
        return 0

    logger.info(f"Embedding {len(df)} FERC orders for RAG...")

    try:
        embedder = SentenceTransformer("all-MiniLM-L6-v2")

        # Use dev path for now (can be made mode-dependent later)
        db_path = Path(__file__).resolve().parent.parent / "data" / "dev" / "lance"
        store = LanceVectorStore(str(db_path), "metis_documents", 384)

    except Exception as e:
        logger.error(f"Failed to initialize RAG store: {e}")
        return 0

    ingested = 0
    for idx, row in df.iterrows():
        try:
            # Use title + summary for embedding context
            text_for_embed = f"{row['title']} {row['summary']}"

            # Create document dict for RAG
            doc = {
                "title": row["title"],
                "content": row["summary"],  # Use summary for RAG retrieval
                "source": "FERC",
                "doc_id": f"ferc_{row['docket_id']}",
                "published_date": row["issued_date"],
                "url": row["full_text_url"],
                "metadata": {
                    "docket_id": row["docket_id"],
                    "order_type": row["order_type"],
                    "subject": row["subject"],
                }
            }

            # Embed and store
            if not mock_mode:
                embedding = embedder.encode(text_for_embed).tolist()
                store.upsert([doc], [embedding])

            ingested += 1
            if (ingested % 10) == 0:
                logger.info(f"  Ingested {ingested}/{len(df)} documents...")

        except Exception as e:
            logger.warning(f"Failed to ingest order {row['docket_id']}: {e}")
            continue

    logger.info(f"✓ Ingested {ingested} FERC orders into RAG")
    return ingested


def ingest_to_sqlite(df: pd.DataFrame) -> int:
    """Store FERC orders in SQLite for reference"""
    if df.empty:
        logger.info("No documents to store in SQLite")
        return 0

    try:
        engine = create_engine(DB_URL)
        df.to_sql("ferc_orders", engine, if_exists="append", index=False)
        logger.info(f"✓ Stored {len(df)} FERC orders in SQLite")
        return len(df)
    except Exception as e:
        logger.error(f"Failed to write to SQLite: {e}")
        return 0


async def fetch_and_ingest_ferc_orders(
    limit: int = 500,
    api_key: Optional[str] = None,
    skip_rag: bool = False
) -> Dict[str, Any]:
    """
    Main async entry point for FERC ingestion (call from orchestrator).

    Args:
        limit: Max orders to fetch
        api_key: Optional API key override
        skip_rag: If True, only store in SQLite (for testing)

    Returns:
        Dict with counts: {"fetched": int, "rag_ingested": int, "db_ingested": int}
    """
    df = fetch_ferc_orders(limit=limit, api_key=api_key)

    result = {
        "fetched": len(df),
        "rag_ingested": 0,
        "db_ingested": 0,
    }

    if df.empty:
        return result

    if not skip_rag:
        result["rag_ingested"] = ingest_to_rag(df)

    result["db_ingested"] = ingest_to_sqlite(df)

    return result


def main():
    """CLI entry point for testing"""
    parser = argparse.ArgumentParser(description="Ingest FERC orders for RAG")
    parser.add_argument("--limit", type=int, default=200, help="Max orders to fetch")
    parser.add_argument("--api-key", help="FERC API key (uses env if not provided)")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually fetch/ingest")
    parser.add_argument("--skip-rag", action="store_true", help="Skip RAG embedding, SQLite only")
    parser.add_argument("--mock-rag", action="store_true", help="Skip actual RAG embedding (testing)")

    args = parser.parse_args()

    logger.info(f"FERC Orders Ingestion")
    logger.info(f"  Limit: {args.limit}")
    logger.info(f"  API Key: {'set' if args.api_key or FERC_API_KEY else 'NOT SET'}")
    logger.info(f"  Mode: {rc.mode_label()}")

    # Fetch from API
    df = fetch_ferc_orders(
        limit=args.limit,
        api_key=args.api_key,
        dry_run=args.dry_run
    )

    if df.empty:
        logger.warning("No orders fetched")
        return

    logger.info(f"Processing {len(df)} orders...")

    # Ingest to RAG (with mock option for testing)
    if not args.skip_rag:
        rag_count = ingest_to_rag(df, mock_mode=args.mock_rag)
        logger.info(f"RAG: {rag_count}/{len(df)} ingested")

    # Ingest to SQLite (if not dry-run)
    if not args.dry_run:
        db_count = ingest_to_sqlite(df)
        logger.info(f"SQLite: {db_count}/{len(df)} ingested")

    logger.info("✓ Complete")


if __name__ == "__main__":
    main()
