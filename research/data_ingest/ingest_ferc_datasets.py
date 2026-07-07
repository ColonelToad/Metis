"""
FERC Dataset Ingestion for RAG Context - Structural Constraints Layer

Fetches FERC datasets related to natural gas infrastructure and market structure:

Dataset 15: Entities to Vertical Assets
  - Transmission assets and capacity
  - Storage facilities
  - Distribution systems
  - Vertical integration info
  - Use for: Understanding pipeline bottlenecks, storage constraints

Dataset 27: NEPA Schedule for Pending Infrastructure Projects
  - Upcoming pipeline projects
  - Infrastructure development timelines
  - NEPA completion schedules
  - Use for: Forward-looking supply constraint context

Stores in LanceDB vector store for RAG Layer 2 (structural constraints).

Usage (standalone test with API key):
    FERC_API_KEY=your_key python research/data_ingest/ingest_ferc_datasets.py --dry-run

Usage (full ingestion):
    FERC_API_KEY=your_key python research/data_ingest/ingest_ferc_datasets.py

Usage (specific dataset only):
    FERC_API_KEY=your_key python research/data_ingest/ingest_ferc_datasets.py --dataset 15
    FERC_API_KEY=your_key python research/data_ingest/ingest_ferc_datasets.py --dataset 27
"""
import os
import sys
import argparse
import logging
import csv
import io
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import requests
import pandas as pd

# Setup logging
logging.basicConfig(level=logging.INFO, format="[FERC Data] %(message)s")
logger = logging.getLogger(__name__)

# Add parent directory to path
# Add research directory to path (for 'common' module)
research_dir = str(Path(__file__).resolve().parent.parent)
if research_dir not in sys.path:
    sys.path.insert(0, research_dir)

# Add project root directory to path (for 'rag' module)
project_root = str(Path(__file__).resolve().parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from common import runtime_config as rc

FERC_API_KEY = os.getenv("FERC_API_KEY")
FERC_API_BASE = "https://api.data.ferc.gov/v1"

DB_URL = rc.get_db_url("sqlite:///data/metis.db")

# Dataset configurations
DATASETS = {
    15: {
        "name": "Entities to Vertical Assets",
        "description": "NG transmission, storage, and distribution assets",
        "category": "infrastructure",
        "columns_to_extract": [
            "Reporting_Entity_Name",
            "Asset_Description",
            "Asset Type",
            "State",
        ]
    },
    27: {
        "name": "NEPA Schedule for Pending Infrastructure Projects",
        "description": "Pending pipeline and infrastructure project timelines",
        "category": "infrastructure",
        "columns_to_extract": [
            "Project Name",
            "Project Type",
            "Status",
            "Target NEPA Completion Date",
            "State",
        ]
    }
}


def fetch_dataset(dataset_id: int, api_key: Optional[str] = None, limit: int = 10000) -> pd.DataFrame:
    """
    Fetch data from a FERC dataset via API.

    Args:
        dataset_id: FERC dataset ID (15 or 27)
        api_key: FERC API key
        limit: Max records to fetch

    Returns:
        DataFrame with dataset contents
    """
    api_key = api_key or FERC_API_KEY

    if not rc.require_real_mode("FERC API"):
        logger.info(f"Skipping dataset {dataset_id} (not in REAL mode)")
        return pd.DataFrame()

    if not api_key:
        logger.warning("FERC_API_KEY not set - skipping FERC ingestion")
        return pd.DataFrame()

    logger.info(f"Fetching dataset {dataset_id} ({DATASETS[dataset_id]['name']})...")

    all_rows = []
    offset = 0
    has_more = True

    try:
        url = f"{FERC_API_BASE}/dataset/{dataset_id}/data"
        
        while has_more:
            params = {
                "api_key": api_key,
                "limit": limit,
                "offset": offset
            }

            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            
            data = resp.json()
            if "row_data" in data:
                all_rows.extend(data["row_data"])
                
                # Check if there are more pages
                has_more = data.get("has_more", False)
                offset += limit
                logger.info(f"Fetched {len(all_rows)} total records so far...")
            else:
                logger.error(f"Unexpected JSON structure in dataset {dataset_id}: missing 'row_data'")
                break

        if all_rows:
            df = pd.DataFrame(all_rows)
            logger.info(f"Finished fetching {len(df)} total records from dataset {dataset_id}")
            return df
        return pd.DataFrame()

    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed for dataset {dataset_id}: {e}")
        return pd.DataFrame()

    # Parse response - FERC API returns CSV
    try:
        data = resp.json()
        if "row_data" in data:
            df = pd.DataFrame(data["row_data"])
            logger.info(f"Fetched {len(df)} records from dataset {dataset_id}")
            return df
        else:
            logger.error(f"Unexpected JSON structure in dataset {dataset_id}: missing 'row_data'")
            return pd.DataFrame()

    except Exception as e:
        logger.error(f"Failed to parse dataset {dataset_id}: {e}")
        return pd.DataFrame()


def process_dataset_15(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Process Entities to Vertical Assets dataset.

    Extract relevant columns and create documents for RAG.
    """
    if df.empty:
        return []

    documents = []

    for _, row in df.iterrows():
        try:
            entity_name = row.get("Reporting_Entity_Name", "")
            asset_desc = row.get("Asset_Description", "")
            asset_type = row.get("Asset Type", "")
            state = row.get("State", "")

            # Create document for RAG
            title = f"{asset_type} - {entity_name}"
            
            # Stitch all the metadata directly into the text content
            content = f"{asset_desc}. "
            if state:
                content += f"Located in {state}. "
            content += f"Entity Name: {entity_name}. Asset Type: {asset_type}."

            doc = {
                "id": f"ferc_15_{str(entity_name).replace(' ', '_')}",
                "title": title,
                "content": content,
                "source": "FERC Dataset 15",
                "published_date": datetime.now(timezone.utc).isoformat(),
                "url": "",
                # Removed the metadata dictionary completely
            }
            documents.append(doc)

        except Exception as e:
            logger.warning(f"Failed to process row: {e}")
            continue

    return documents


def process_dataset_27(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Process NEPA Schedule dataset.

    Extract project information and create documents for RAG.
    """
    if df.empty:
        return []

    documents = []

    for _, row in df.iterrows():
        try:
            project_name = row.get("Project_Name", "")
            nepa_date = row.get("Final_NEPA_Document_Target_Issuance_Date", "")
            project_type = row.get("NEPA_Document_Type", "") 
            # Create document for RAG
            title = f"{project_type} Project: {project_name}" if project_type else f"Project: {project_name}"
            
            # Stitch all the metadata directly into the text content
            content = f"Target NEPA completion: {nepa_date}. "
            if project_type:
                content += f"Project Type: {project_type}."

            doc = {
                "id": f"ferc_27_{str(project_name).replace(' ', '_')}",
                "title": title,
                "content": content,
                "source": "FERC Dataset 27",
                "published_date": datetime.now(timezone.utc).isoformat(),
                "url": "",
                # Removed the metadata dictionary completely
            }
            documents.append(doc)

        except Exception as e:
            logger.warning(f"Failed to process row: {e}")
            continue

    return documents


def ingest_to_rag(documents: List[Dict[str, Any]], dataset_id: int, mock_mode: bool = False) -> int:
    """
    Embed documents into LanceDB for RAG retrieval.
    """
    if not documents:
        logger.info(f"No documents to ingest for dataset {dataset_id}")
        return 0

    try:
        from rag.vectorstore.lancedb_store import LanceVectorStore
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        logger.error(f"Missing RAG dependencies: {e}")
        return 0

    logger.info(f"Embedding {len(documents)} documents from dataset {dataset_id}...")

    try:
        embedder = SentenceTransformer("all-MiniLM-L6-v2")
        db_path = Path(__file__).resolve().parent.parent / "data" / "dev" / "lance"
        store = LanceVectorStore(str(db_path), "metis_documents", 384)

    except Exception as e:
        logger.error(f"Failed to initialize RAG store: {e}")
        return 0

    ingested = 0
    BATCH_SIZE = 256  # You can adjust this based on your memory (256-512 is usually a sweet spot)

    # Process in batches
    for i in range(0, len(documents), BATCH_SIZE):
        batch = documents[i : i + BATCH_SIZE]
        
        try:
            if not mock_mode:
                # 1. Prepare all texts for this batch
                texts_for_embed = [f"{doc['title']} {doc['content']}" for doc in batch]
                
                # 2. Encode the entire batch at once (massively faster)
                embeddings_array = embedder.encode(texts_for_embed).tolist()
                
                # 3. Attach embeddings back to the document dictionaries
                for doc, embedding in zip(batch, embeddings_array):
                    doc["embedding"] = embedding
                
                # 4. Upsert the entire batch into LanceDB in one transaction
                store.upsert(batch)

            ingested += len(batch)
            logger.info(f"  Ingested {ingested}/{len(documents)}...")

        except Exception as e:
            logger.warning(f"Failed to ingest batch starting at index {i}: {e}")
            continue

    logger.info(f"✓ Ingested {ingested} documents from dataset {dataset_id}")
    return ingested


async def fetch_and_ingest_ferc_datasets(
    dataset_ids: Optional[List[int]] = None,
    api_key: Optional[str] = None,
    skip_rag: bool = False
) -> Dict[str, Any]:
    """
    Main async entry point for FERC dataset ingestion.

    Args:
        dataset_ids: List of dataset IDs to ingest (default: [15, 27])
        api_key: Optional API key override
        skip_rag: If True, skip RAG embedding

    Returns:
        Dict with ingestion stats
    """
    if dataset_ids is None:
        dataset_ids = [15, 27]

    result = {
        "datasets": {}
    }

    for dataset_id in dataset_ids:
        if dataset_id not in DATASETS:
            logger.warning(f"Unknown dataset ID: {dataset_id}")
            continue

        logger.info(f"\n--- Processing Dataset {dataset_id} ---")

        # Fetch data
        df = fetch_dataset(dataset_id, api_key=api_key)
        if df.empty:
            result["datasets"][dataset_id] = {"fetched": 0, "ingested": 0}
            continue

        # Process into documents
        if dataset_id == 15:
            documents = process_dataset_15(df)
        elif dataset_id == 27:
            documents = process_dataset_27(df)
        else:
            documents = []

        # Ingest to RAG
        if not skip_rag and documents:
            ingested = ingest_to_rag(documents, dataset_id)
        else:
            ingested = 0

        result["datasets"][dataset_id] = {
            "fetched": len(df),
            "documents": len(documents),
            "ingested": ingested
        }

    return result


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(description="Ingest FERC datasets for RAG")
    parser.add_argument(
        "--dataset",
        type=int,
        help="Specific dataset ID to ingest (15 or 27, default: both)"
    )
    parser.add_argument("--api-key", help="FERC API key (uses env if not provided)")
    parser.add_argument("--dry-run", action="store_true", help="Don't fetch, just show config")
    parser.add_argument("--skip-rag", action="store_true", help="Skip RAG embedding")

    args = parser.parse_args()

    logger.info("FERC Dataset Ingestion")
    logger.info(f"  Mode: {rc.mode_label()}")
    logger.info(f"  API Key: {'SET' if args.api_key or FERC_API_KEY else 'NOT SET'}")

    if args.dry_run:
        logger.info("\nDRY RUN - Configuration:")
        for ds_id, config in DATASETS.items():
            if args.dataset and args.dataset != ds_id:
                continue
            logger.info(f"\n  Dataset {ds_id}: {config['name']}")
            logger.info(f"    Description: {config['description']}")
            logger.info(f"    Endpoint: {FERC_API_BASE}/dataset/{ds_id}/data?api_key=...")
        return

    # Determine which datasets to ingest
    dataset_ids = [args.dataset] if args.dataset else [15, 27]

    # Run async ingestion
    import asyncio
    result = asyncio.run(fetch_and_ingest_ferc_datasets(
        dataset_ids=dataset_ids,
        api_key=args.api_key,
        skip_rag=args.skip_rag
    ))

    # Summary
    logger.info("\n" + "="*60)
    logger.info("INGESTION SUMMARY")
    logger.info("="*60)
    for ds_id, stats in result.get("datasets", {}).items():
        logger.info(
            f"\nDataset {ds_id}: "
            f"Fetched={stats['fetched']}, "
            f"Ingested={stats['ingested']}"
        )

    logger.info("\n✓ Complete")


if __name__ == "__main__":
    main()
