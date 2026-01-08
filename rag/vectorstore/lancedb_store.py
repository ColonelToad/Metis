from __future__ import annotations
import os
from pathlib import Path
from typing import List, Dict, Optional

import pyarrow as pa
from lancedb import connect


class LanceVectorStore:
    """Lightweight LanceDB-backed vector store for documents.

    Table schema:
    - id: string (primary key)
    - embedding: fixed_size_list<float32>
    - title: string
    - content: string
    - source: string
    - published_date: string (ISO)
    - url: string
    """

    def __init__(self, db_path: Path, collection_name: str, embedding_dim: int):
        self.db_path = Path(db_path)
        self.collection_name = collection_name
        self.embedding_dim = embedding_dim

        self.db_path.mkdir(parents=True, exist_ok=True)
        self.db = connect(str(self.db_path))

        def create_table():
            schema = pa.schema([
                pa.field("id", pa.string()),
                pa.field("embedding", pa.list_(pa.float32(), self.embedding_dim)),
                pa.field("title", pa.string()),
                pa.field("content", pa.string()),
                pa.field("source", pa.string()),
                pa.field("published_date", pa.string()),
                pa.field("url", pa.string()),
            ])
            return self.db.create_table(self.collection_name, schema=schema)

        if self.collection_name in self.db.table_names():
            tbl = self.db.open_table(self.collection_name)
            emb_field = tbl.schema.field("embedding")
            is_fixed = emb_field is not None and emb_field.type.list_size == self.embedding_dim
            if not is_fixed:
                self.db.drop_table(self.collection_name)
                self.table = create_table()
            else:
                self.table = tbl
        else:
            self.table = create_table()

    def upsert(self, docs: List[Dict]):
        """Insert or update documents.
        Each doc must include: id, embedding, title, content, source, published_date, url
        """
        self.table.add(docs)

    def search(self, query_embedding: List[float], top_k: int = 3, source_filter: Optional[str] = None) -> List[Dict]:
        q = self.table.search(query_embedding, vector_column_name="embedding")
        if source_filter:
            q = q.where(f"source = '{source_filter}'")
        res = (
            q
            .limit(top_k)
            .select(["id", "title", "content", "source", "published_date", "url"])
            .to_pandas()
        )
        out = []
        for _, row in res.iterrows():
            out.append({
                "doc_id": row["id"],
                "score": float(row.get("_distance", 0.0)),
                "title": row["title"],
                "content": row["content"],
                "source": row["source"],
                "published_date": row["published_date"],
                "url": row.get("url", ""),
            })
        return out
