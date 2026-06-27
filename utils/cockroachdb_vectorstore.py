"""Backward-compat re-export. Use integrations.vectorstore.cockroach_store instead."""
from integrations.vectorstore.cockroach_store import CockroachVectorStore, CONNECTION_STRING

__all__ = ["CockroachVectorStore", "CONNECTION_STRING"]
