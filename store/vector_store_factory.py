"""Vector store factory.

Selects between FAISS and LanceDB based on config or CLI flag.
"""
from __future__ import annotations


def get_vector_store(backend: str | None = None):
    """Return a vector store instance for the chosen backend.

    Args:
        backend: "faiss" | "lancedb". None reads from config.
    """
    if backend is None:
        from config import DEFAULT_VECTOR_BACKEND
        backend = DEFAULT_VECTOR_BACKEND

    if backend == "lancedb":
        from store.lancedb_index import LanceDBVectorIndex
        return LanceDBVectorIndex()
    else:
        from store.vector_index import VectorIndex
        return VectorIndex()
