"""
Document ingestion for RAG corpus.
Fetches and processes documents from EIA, Congress.gov, FERC, and weather services.
"""
import requests
from bs4 import BeautifulSoup
from typing import List, Optional
from datetime import datetime, timedelta
from pathlib import Path
import json
from loguru import logger

from retrieval_pipeline import Document, RAGPipeline


class DocumentIngester:
    """Ingest documents from various sources for RAG indexing."""
    
    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or Path("data/documents")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def fetch_eia_reports(self, num_reports: int = 10) -> List[Document]:
        """
        Fetch recent EIA natural gas storage reports.
        
        Args:
            num_reports: Number of recent reports to fetch
        
        Returns:
            List of Document objects
        """
        documents = []
        
        # EIA Natural Gas Weekly Update
        base_url = "https://www.eia.gov/naturalgas/weekly/"
        
        try:
            # For now, create sample documents
            # In production, scrape actual EIA reports
            for i in range(num_reports):
                date = datetime.now() - timedelta(weeks=i)
                
                doc = Document(
                    doc_id=f"EIA-{date.strftime('%Y%m%d')}",
                    title=f"Natural Gas Weekly Update - {date.strftime('%B %d, %Y')}",
                    content=f"Sample EIA report content for week of {date.strftime('%Y-%m-%d')}. Working gas in storage was X Bcf.",
                    source="EIA",
                    published_date=date,
                    url=f"{base_url}archive/",
                )
                documents.append(doc)
            
            logger.info(f"Fetched {len(documents)} EIA reports")
            
        except Exception as e:
            logger.error(f"Failed to fetch EIA reports: {e}")
        
        return documents
    
    def fetch_congress_bills(self, topic: str = "energy") -> List[Document]:
        """
        Fetch recent congressional bills related to energy.
        Uses Congress.gov API.
        
        Args:
            topic: Topic to search for
        
        Returns:
            List of Document objects
        """
        documents = []
        
        # Congress.gov API endpoint
        # Note: Requires API key from congress.gov
        api_url = "https://api.congress.gov/v3/bill"
        
        # Sample bills for demonstration
        sample_bills = [
            {
                "bill_id": "HR-1234",
                "title": "Clean Energy Tax Credit Extension Act",
                "summary": "Extends tax credits for renewable energy production through 2030.",
                "date": datetime(2024, 1, 15),
            },
            {
                "bill_id": "S-5678",
                "title": "Natural Gas Infrastructure Modernization Act",
                "summary": "Authorizes funding for pipeline safety upgrades and LNG export terminals.",
                "date": datetime(2023, 12, 20),
            },
        ]
        
        for bill in sample_bills:
            doc = Document(
                doc_id=f"CONGRESS-{bill['bill_id']}",
                title=bill['title'],
                content=f"{bill['title']}. {bill['summary']}",
                source="Congress",
                published_date=bill['date'],
                url=f"https://www.congress.gov/bill/{bill['bill_id']}",
            )
            documents.append(doc)
        
        logger.info(f"Fetched {len(documents)} congressional bills")
        return documents
    
    def fetch_ferc_orders(self, num_orders: int = 5) -> List[Document]:
        """
        Fetch recent FERC orders related to natural gas markets.
        
        Args:
            num_orders: Number of recent orders to fetch
        
        Returns:
            List of Document objects
        """
        documents = []
        
        sample_orders = [
            {
                "order_id": "RM24-1",
                "title": "Pipeline Rate Filing Requirements",
                "summary": "Establishes new requirements for interstate natural gas pipeline rate filings.",
                "date": datetime(2024, 1, 10),
            },
        ]
        
        for order in sample_orders:
            doc = Document(
                doc_id=f"FERC-{order['order_id']}",
                title=order['title'],
                content=f"FERC Order {order['order_id']}: {order['summary']}",
                source="FERC",
                published_date=order['date'],
                url=f"https://www.ferc.gov/",
            )
            documents.append(doc)
        
        logger.info(f"Fetched {len(documents)} FERC orders")
        return documents
    
    def fetch_weather_advisories(self) -> List[Document]:
        """
        Fetch weather advisories that could impact energy demand.
        
        Returns:
            List of Document objects
        """
        documents = []
        
        # Sample weather advisories
        sample_advisories = [
            {
                "advisory_id": "NWS-2024-001",
                "title": "Extreme Cold Warning - Northeast",
                "content": "Arctic air mass will bring temperatures 20-30°F below normal across the Northeast Jan 10-15. Expect record heating demand.",
                "date": datetime(2024, 1, 8),
            },
            {
                "advisory_id": "NWS-2024-002",
                "title": "Heat Wave - Southwest",
                "content": "Excessive heat expected across Southwest with temperatures 10-15°F above normal. Increased cooling demand forecast.",
                "date": datetime(2023, 7, 20),
            },
        ]
        
        for advisory in sample_advisories:
            doc = Document(
                doc_id=f"WEATHER-{advisory['advisory_id']}",
                title=advisory['title'],
                content=advisory['content'],
                source="Weather",
                published_date=advisory['date'],
            )
            documents.append(doc)
        
        logger.info(f"Fetched {len(documents)} weather advisories")
        return documents
    
    def ingest_all(self, rag_pipeline: RAGPipeline):
        """
        Fetch documents from all sources and index them.
        
        Args:
            rag_pipeline: RAG pipeline instance for indexing
        """
        all_docs = []
        
        # Fetch from all sources
        all_docs.extend(self.fetch_eia_reports(num_reports=10))
        all_docs.extend(self.fetch_congress_bills())
        all_docs.extend(self.fetch_ferc_orders())
        all_docs.extend(self.fetch_weather_advisories())
        
        # Index in batch
        logger.info(f"Indexing {len(all_docs)} documents...")
        rag_pipeline.index_documents_batch(all_docs)
        logger.info("Document ingestion complete")


if __name__ == "__main__":
    # Initialize RAG pipeline
    rag = RAGPipeline()
    
    # Initialize ingester and fetch documents
    ingester = DocumentIngester()
    ingester.ingest_all(rag)
    
    # Test retrieval
    query = "natural gas storage heating demand cold weather"
    results = rag.retrieve(query, top_k=3)
    
    print(f"\nTop {len(results)} results for query: '{query}'")
    for i, result in enumerate(results, 1):
        print(f"\n{i}. {result['title']}")
        print(f"   Source: {result['source']}, Score: {result['score']:.4f}")
        print(f"   {result['content'][:200]}...")
