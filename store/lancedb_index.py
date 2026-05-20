"""LanceDB vector store backend.

Stores image embeddings alongside metadata (tags, collection_id) in Lance format.
Supports filtered vector search using LanceDB's .where() clause.
"""
from __future__ import annotations

import numpy as np
from pathlib import Path

from config import LANCEDB_DIR


class LanceDBVectorIndex:
    def __init__(self, dimension: int = 512, db_path: str | None = None):
        self.dimension = dimension
        self.db_path = db_path or str(LANCEDB_DIR)
        self.db = None
        self.table = None

    def _connect(self):
        if self.db is None:
            import lancedb
            Path(self.db_path).mkdir(parents=True, exist_ok=True)
            self.db = lancedb.connect(self.db_path)
            existing = self.db.table_names()
            if "images" in existing:
                self.table = self.db.open_table("images")

    def _ensure_table(self):
        self._connect()
        if self.table is None:
            import pyarrow as pa
            schema = pa.schema([
                pa.field("image_id", pa.int64()),
                pa.field("vector", pa.list_(pa.float32(), self.dimension)),
                pa.field("tags", pa.string()),
                pa.field("collection_id", pa.int64()),
            ])
            self.db.create_table("images", schema=schema)
            self.table = self.db.open_table("images")

    def add(self, image_id: int, embedding: np.ndarray, metadata: dict | None = None):
        """Add a single embedding with optional metadata."""
        self._ensure_table()
        meta = metadata or {}

        if embedding.shape[0] != self.dimension:
            if embedding.shape[0] > self.dimension:
                embedding = embedding[:self.dimension]
            else:
                embedding = np.pad(embedding, (0, self.dimension - embedding.shape[0]))

        import pyarrow as pa
        record = {
            "image_id": image_id,
            "vector": embedding.tolist(),
            "tags": meta.get("tags", ""),
            "collection_id": meta.get("collection_id", 0),
        }
        self.table.add([record])

    def search(self, query_embedding: np.ndarray, top_k: int = 10) -> list[tuple[int, float]]:
        """Vector similarity search. Returns list of (image_id, score)."""
        self._connect()
        if self.table is None:
            return []

        if query_embedding.shape[0] != self.dimension:
            if query_embedding.shape[0] > self.dimension:
                query_embedding = query_embedding[:self.dimension]
            else:
                query_embedding = np.pad(query_embedding, (0, self.dimension - query_embedding.shape[0]))

        results = (
            self.table.search(query_embedding.tolist())
            .limit(top_k)
            .select(["image_id"])
            .to_pandas()
        )
        return [(int(row["image_id"]), float(row["_distance"])) for _, row in results.iterrows()]

    def search_by_text(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        """Text-to-image search via CLIP text encoding."""
        from store.embedding_utils import encode_text
        query_embedding = encode_text(query)
        return self.search(query_embedding, top_k)

    def search_filtered(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
        tags: list[str] | None = None,
        collection_id: int | None = None,
    ) -> list[tuple[int, float]]:
        """Filtered vector search — unique to LanceDB."""
        self._connect()
        if self.table is None:
            return []

        if query_embedding.shape[0] != self.dimension:
            if query_embedding.shape[0] > self.dimension:
                query_embedding = query_embedding[:self.dimension]
            else:
                query_embedding = np.pad(query_embedding, (0, self.dimension - query_embedding.shape[0]))

        query = self.table.search(query_embedding.tolist()).limit(top_k).select(["image_id"])

        conditions = []
        if collection_id is not None:
            conditions.append(f"collection_id = {collection_id}")
        if tags:
            tag_conds = " OR ".join(f'tags LIKE "%{t}%"' for t in tags)
            conditions.append(f"({tag_conds})")

        if conditions:
            query = query.where(" AND ".join(conditions))

        results = query.to_pandas()
        return [(int(row["image_id"]), float(row["_distance"])) for _, row in results.iterrows()]

    def save(self):
        """LanceDB auto-persists. No-op for interface compatibility."""
        pass

    def load(self):
        """Open existing table. Called by __init__ indirectly via _connect."""
        self._connect()
