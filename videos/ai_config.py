"""DEPRECATED: use integrations.registry directly."""
from langchain_text_splitters import RecursiveCharacterTextSplitter

from integrations.registry import (
    LLM_MAX_OUTPUT_TOKENS,
    get_embeddings,
    get_llm,
    get_vectorstore,
    _LazyProxy,
)

CHUNK_SIZE = 800
CHUNK_OVERLAP = 50
TEXT_SPLITTER = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
EMBEDDING_MODEL = _LazyProxy(get_embeddings)
VECTOR_STORE = _LazyProxy(get_vectorstore)

__all__ = [
    "get_llm",
    "get_embeddings",
    "get_vectorstore",
    "EMBEDDING_MODEL",
    "TEXT_SPLITTER",
    "VECTOR_STORE",
    "LLM_MAX_OUTPUT_TOKENS",
]
