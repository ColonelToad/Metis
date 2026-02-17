"""
RAG (Retrieval-Augmented Generation) pipeline for policy/climate document retrieval.
Provides context for trading signal explanations.
"""
from typing import List, Dict, Optional
from pathlib import Path
import json
from dataclasses import dataclass, asdict
from datetime import datetime

import os
import sys
from sentence_transformers import SentenceTransformer
try:
    from pymilvus import connections, Collection, CollectionSchema, FieldSchema, DataType, utility
except Exception:
    connections = None
    Collection = None
    CollectionSchema = None
    FieldSchema = None
    DataType = None
    utility = None
from loguru import logger
from pathlib import Path as _Path
sys.path.append(str(_Path(__file__).resolve().parents[1]))
from rag.vectorstore.lancedb_store import LanceVectorStore


@dataclass
class Document:
    """Represents a document in the RAG corpus."""
    doc_id: str
    title: str
    content: str
    source: str  # "EIA", "FERC", "Congress", "Weather"
    published_date: datetime
    url: Optional[str] = None
    metadata: Optional[Dict] = None


class RAGPipeline:
    """
    RAG pipeline for retrieving relevant policy/climate documents.
    Uses LanceDB (default) or Milvus for vector storage and sentence-transformers for embeddings.
    """
    
    def __init__(
        self,
        collection_name: str = "metis_documents",
        embedding_model: str = "all-MiniLM-L6-v2",
        vector_backend: str = None,  # "lance" (default) or "milvus"
        milvus_host: str = "localhost",
        milvus_port: int = 19530,
    ):
        self.collection_name = collection_name
        self.embedding_model = SentenceTransformer(embedding_model)
        self.embedding_dim = self.embedding_model.get_sentence_embedding_dimension()
        
        # Retrieval mode: "normal" (live), "test" (from test file), "mock" (hardcoded)
        self.retrieval_mode = os.getenv("RAG_RETRIEVAL_MODE", "normal").lower()
        
        # Backend selection
        self.vector_backend = (vector_backend or os.getenv("VECTOR_BACKEND", "lance")).lower()
        self.collection = None
        self.lance = None

        if self.retrieval_mode == "test":
            logger.info("RAG Retrieval Mode: TEST (loading from test documents)")
            self._load_test_documents()
        elif self.retrieval_mode == "mock":
            logger.info("RAG Retrieval Mode: MOCK (using hardcoded documents)")
            self._init_mock_documents()
        else:
            logger.info("RAG Retrieval Mode: NORMAL (live retrieval)")
            
            if self.vector_backend == "milvus":
                if connections is None:
                    raise RuntimeError("Milvus backend selected but pymilvus is not installed. Install pymilvus or set VECTOR_BACKEND=lance.")
                connections.connect("default", host=milvus_host, port=19530)
                logger.info(f"Connected to Milvus at {milvus_host}:{milvus_port}")
                self._init_collection()
            else:
                # Default to LanceDB; pick mode-specific path
                mode = os.getenv("METIS_MODE", "DEV").upper()
                base_dir = _Path(__file__).resolve().parents[1]
                db_dir = base_dir / ("data/lance" if mode == "REAL" else "data/dev/lance")
                self.lance = LanceVectorStore(db_dir, self.collection_name, self.embedding_dim)
                logger.info(f"Connected to LanceDB at {db_dir}")
    
    def _load_test_documents(self):
        """Load test documents from test_documents.json for testing."""
        test_file = _Path(__file__).resolve().parent / "tests" / "test_documents.json"
        if test_file.exists():
            try:
                with open(test_file, 'r') as f:
                    self.test_documents = json.load(f)
                logger.info(f"Loaded {len(self.test_documents)} test documents")
            except Exception as e:
                logger.error(f"Failed to load test documents: {e}")
                self.test_documents = self._get_default_mock_documents()
        else:
            logger.warning(f"Test documents file not found: {test_file}")
            self.test_documents = self._get_default_mock_documents()
    
    def _init_mock_documents(self):
        """Initialize hardcoded mock documents for CI/CD and testing."""
        self.mock_documents = self._get_default_mock_documents()
        logger.info(f"Initialized {len(self.mock_documents)} mock documents")
    
    @staticmethod
    def _get_default_mock_documents() -> List[Dict]:
        """Return default mock documents for testing without external dependencies."""
        return [
            {
                "doc_id": "mock_eia_001",
                "title": "EIA Weekly Natural Gas Storage Report",
                "content": """Working gas inventories in the United States totaled 1,847 billion cubic feet (Bcf) 
for the week ended February 16, 2026. This represents a decrease of 23 Bcf from the previous week.
The current level is 95% of the 5-year average. Storage withdrawals during winter months are normal
as demand increases due to heating season.""",
                "source": "EIA",
                "published_date": datetime.utcnow().isoformat(),
                "url": "https://www.eia.gov/",
                "score": 0.95,
            },
            {
                "doc_id": "mock_weather_001",
                "title": "NOAA Arctic Oscillation Analysis",
                "content": """Arctic Oscillation Index shows strongly negative phase with 89% model agreement.
Temperature anomalies: Northern US +8.5°F, Central US +6.2°F. Cold pool expected to persist
through February with 70% probability. Confidence: HIGH based on GFS, ECMWF, GEFS ensemble agreement.""",
                "source": "NOAA",
                "published_date": datetime.utcnow().isoformat(),
                "url": "https://www.noaa.gov/",
                "score": 0.92,
            },
            {
                "doc_id": "mock_congress_001",
                "title": "S.567 Clean Energy Infrastructure Bill - Status Update",
                "content": """S.567 (Clean Energy Infrastructure Bill) passed Senate Energy Committee on Feb 14, 2026
with 12-8 bipartisan vote. Bill includes $50B for transmission upgrades and natural gas infrastructure.
Expected floor vote in Senate within 2 weeks. House companion bill H.R.1234 has 47 cosponsors.
Implications: Increased capex requirements for utilities, potential long-term demand supports.""",
                "source": "Congress",
                "published_date": datetime.utcnow().isoformat(),
                "url": "https://congress.gov/",
                "score": 0.88,
            },
        ]

    
    def _init_collection(self):
        """Initialize Milvus collection for document embeddings."""
        if utility.has_collection(self.collection_name):
            self.collection = Collection(self.collection_name)
            logger.info(f"Loaded existing collection: {self.collection_name}")
        else:
            # Create new collection
            fields = [
                FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=200),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.embedding_dim),
                FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=500),
                FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=10000),
                FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=100),
                FieldSchema(name="published_date", dtype=DataType.VARCHAR, max_length=50),
                FieldSchema(name="url", dtype=DataType.VARCHAR, max_length=500),
            ]
            
            schema = CollectionSchema(fields, description="Metis document corpus")
            self.collection = Collection(self.collection_name, schema)
            
            # Create index for fast similarity search
            index_params = {
                "metric_type": "L2",
                "index_type": "IVF_FLAT",
                "params": {"nlist": 128}
            }
            self.collection.create_index("embedding", index_params)
            logger.info(f"Created new collection: {self.collection_name}")
        
        self.collection.load()
    
    def index_document(self, doc: Document) -> bool:
        """
        Add a document to the vector index.
        
        Args:
            doc: Document to index
        
        Returns:
            True if successful
        """
        try:
            # Generate embedding
            embedding = self.embedding_model.encode(doc.content)

            if self.vector_backend == "milvus":
                entities = [
                    [doc.doc_id],
                    [embedding.tolist()],
                    [doc.title],
                    [doc.content[:10000]],
                    [doc.source],
                    [doc.published_date.isoformat()],
                    [doc.url or ""],
                ]
                self.collection.insert(entities)
            else:
                self.lance.upsert([
                    {
                        "id": doc.doc_id,
                        "embedding": embedding.tolist(),
                        "title": doc.title,
                        "content": doc.content[:10000],
                        "source": doc.source,
                        "published_date": doc.published_date.isoformat(),
                        "url": doc.url or "",
                    }
                ])
            logger.debug(f"Indexed document: {doc.doc_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to index document {doc.doc_id}: {e}")
            return False
    
    def index_documents_batch(self, docs: List[Document], batch_size: int = 100):
        """
        Index multiple documents in batches.
        
        Args:
            docs: List of documents to index
            batch_size: Number of documents per batch
        """
        for i in range(0, len(docs), batch_size):
            batch = docs[i:i + batch_size]
            
            ids = [doc.doc_id for doc in batch]
            embeddings = self.embedding_model.encode([doc.content for doc in batch])
            titles = [doc.title for doc in batch]
            contents = [doc.content[:10000] for doc in batch]
            sources = [doc.source for doc in batch]
            dates = [doc.published_date.isoformat() for doc in batch]
            urls = [doc.url or "" for doc in batch]
            
            if self.vector_backend == "milvus":
                entities = [ids, embeddings.tolist(), titles, contents, sources, dates, urls]
                self.collection.insert(entities)
            else:
                payload = []
                for j, doc in enumerate(batch):
                    payload.append({
                        "id": doc.doc_id,
                        "embedding": embeddings[j].tolist(),
                        "title": doc.title,
                        "content": doc.content[:10000],
                        "source": doc.source,
                        "published_date": doc.published_date.isoformat(),
                        "url": doc.url or "",
                    })
                self.lance.upsert(payload)
            logger.info(f"Indexed batch {i // batch_size + 1}: {len(batch)} documents")
        
        if self.vector_backend == "milvus":
            self.collection.flush()
    
    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        source_filter: Optional[str] = None
    ) -> List[Dict]:
        """
        Retrieve most relevant documents for a query with mode-aware behavior.
        
        Modes:
        - "normal": Live retrieval from vector database (LanceDB/Milvus)
        - "test": Return documents from test_documents.json
        - "mock": Return hardcoded mock documents
        
        Args:
            query: Query text
            top_k: Number of documents to retrieve
            source_filter: Optional source type filter ("EIA", "FERC", etc.)
        
        Returns:
            List of retrieved documents with scores
        """
        logger.info(f"Retrieving documents for query: '{query[:80]}...' (mode={self.retrieval_mode}, top_k={top_k})")
        
        # Test mode: return documents from test file
        if self.retrieval_mode == "test":
            logger.debug(f"Test mode: returning up to {top_k} test documents")
            docs = getattr(self, 'test_documents', [])
            if source_filter:
                docs = [d for d in docs if d.get("source") == source_filter]
            return docs[:top_k]
        
        # Mock mode: return hardcoded documents
        if self.retrieval_mode == "mock":
            logger.debug(f"Mock mode: returning up to {top_k} mock documents")
            docs = getattr(self, 'mock_documents', self._get_default_mock_documents())
            if source_filter:
                docs = [d for d in docs if d.get("source") == source_filter]
            return docs[:top_k]
        
        # Normal mode: live retrieval from vector database
        # Generate query embedding
        query_embedding = self.embedding_model.encode(query)
        
        if self.vector_backend == "milvus":
            expr = None
            if source_filter:
                expr = f'source == "{source_filter}"'
            search_params = {"metric_type": "L2", "params": {"nprobe": 10}}
            results = self.collection.search(
                data=[query_embedding.tolist()],
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                expr=expr,
                output_fields=["title", "content", "source", "published_date", "url"]
            )
            retrieved_docs = []
            for hits in results:
                for hit in hits:
                    retrieved_docs.append({
                        "doc_id": hit.id,
                        "score": float(hit.distance),
                        "title": hit.entity.get("title"),
                        "content": hit.entity.get("content"),
                        "source": hit.entity.get("source"),
                        "published_date": hit.entity.get("published_date"),
                        "url": hit.entity.get("url"),
                    })
            return retrieved_docs
        else:
            return self.lance.search(query_embedding.tolist(), top_k=top_k, source_filter=source_filter)
    
    def generate_explanation(
        self,
        signal: Dict,
        retrieved_docs: List[Dict],
        llm_client=None  # OpenAI/Anthropic client
    ) -> str:
        """
        Generate LLM explanation for a trading signal using retrieved context.
        
        Args:
            signal: Trading signal dictionary
            retrieved_docs: Documents retrieved from vector DB
            llm_client: LLM client (OpenAI/Anthropic)
        
        Returns:
            Generated explanation text
        """
        # Build context from retrieved documents
        context_parts = []
        for i, doc in enumerate(retrieved_docs, 1):
            context_parts.append(
                f"[{i}] {doc['title']} ({doc['source']}, {doc['published_date']})\n"
                f"{doc['content'][:500]}..."
            )
        
        context = "\n\n".join(context_parts)
        
        # Build prompt
        prompt = f"""You are a quantitative trading analyst explaining a natural gas trading signal.

Signal Details:
- Symbol: {signal['symbol']}
- Direction: {signal['direction']}
- Confidence: {signal['confidence']:.2%}
- Quantity: {signal['target_quantity']} contracts

Model Features:
{', '.join(signal.get('metadata', {}).get('features_used', []))}

Weather Anomaly: {signal.get('metadata', {}).get('weather_anomaly')}
Policy Trigger: {signal.get('metadata', {}).get('policy_trigger')}

Relevant Context Documents:
{context}

Based on this information, provide a concise (2-3 sentences) explanation of why this trading signal was generated. Focus on the relationship between the climate/policy factors and expected price movement.
"""
        
        # TODO: Call LLM API (OpenAI/Anthropic)
        # For now, return a template explanation
        explanation = (
            f"The model recommends a {signal['direction']} position on {signal['symbol']} "
            f"with {signal['confidence']:.1%} confidence. This signal is driven by "
            f"{len(signal.get('metadata', {}).get('features_used', []))} features including weather anomalies "
            f"and policy indicators. Retrieved documents suggest relevant market conditions supporting this forecast."
        )
        
        return explanation


if __name__ == "__main__":
    # Example usage
    rag = RAGPipeline()
    
    # Index sample documents
    sample_docs = [
        Document(
            doc_id="EIA-001",
            title="Weekly Natural Gas Storage Report",
            content="Natural gas inventories decreased by 150 Bcf last week, larger than the 5-year average draw of 120 Bcf. Cold weather in the Northeast drove higher heating demand.",
            source="EIA",
            published_date=datetime(2024, 1, 4),
            url="https://www.eia.gov/naturalgas/weekly/",
        ),
        Document(
            doc_id="WEATHER-001",
            title="Arctic Blast Forecast for Northeast",
            content="A major cold air outbreak is expected to bring temperatures 15-20°F below normal across the Northeast and Midwest January 10-15. Heating degree days will spike significantly.",
            source="Weather",
            published_date=datetime(2024, 1, 5),
        ),
    ]
    
    for doc in sample_docs:
        rag.index_document(doc)
    
    # Test retrieval
    query = "natural gas demand heating cold weather"
    results = rag.retrieve(query, top_k=2)
    
    print(f"Retrieved {len(results)} documents:")
    for result in results:
        print(f"  - {result['title']} (score: {result['score']:.4f})")
