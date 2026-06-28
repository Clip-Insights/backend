"""Unit tests for the provider registry, API-key rotation and the no-op LLM.

These are pure-logic tests (no DB, no network), so they are written as plain
functions and run quickly under both pytest and Django's test runner.
"""
import pytest
from pydantic import BaseModel

from integrations import registry
from integrations.embeddings.noop import NOOP_DIMENSIONS, NoopEmbeddings
from integrations.keys import APIKeyManager, load_api_keys
from integrations.llm.noop import NoopLLM
from integrations.vectorstore.memory import MemoryVectorStore


# --------------------------------------------------------------------------- #
# APIKeyManager
# --------------------------------------------------------------------------- #
def test_key_manager_rotates_round_robin():
    manager = APIKeyManager(["a", "b", "c"])
    assert [manager.get_next_key() for _ in range(4)] == ["a", "b", "c", "a"]


def test_key_manager_requires_at_least_one_key():
    with pytest.raises(ValueError):
        APIKeyManager([])


def test_load_api_keys_splits_and_strips(monkeypatch):
    monkeypatch.setenv("MY_KEYS", " k1 , k2 ,, k3 ")
    assert load_api_keys("MY_KEYS") == ["k1", "k2", "k3"]


def test_load_api_keys_missing_raises(monkeypatch):
    monkeypatch.delenv("MY_KEYS", raising=False)
    with pytest.raises(ValueError):
        load_api_keys("MY_KEYS")


# --------------------------------------------------------------------------- #
# Provider registry
# --------------------------------------------------------------------------- #
def test_registry_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "does-not-exist")
    registry._singletons.clear()
    with pytest.raises(ValueError):
        registry.get_llm()


def test_registry_returns_singleton(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "noop")
    registry._singletons.clear()
    first = registry.get_llm()
    second = registry.get_llm()
    assert first is second
    assert isinstance(first, NoopLLM)


def test_registry_resolves_embeddings_and_vectorstore(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "noop")
    monkeypatch.setenv("VECTORSTORE_PROVIDER", "memory")
    registry._singletons.clear()
    assert isinstance(registry.get_embeddings(), NoopEmbeddings)
    assert isinstance(registry.get_vectorstore(), MemoryVectorStore)
    # Singleton per provider.
    assert registry.get_vectorstore() is registry.get_vectorstore()


# --------------------------------------------------------------------------- #
# NoopLLM
# --------------------------------------------------------------------------- #
def test_noop_complete_and_stream():
    llm = NoopLLM()
    assert llm.complete("hi") == "[noop llm response]"
    assert list(llm.stream("hi")) == ["[noop llm response]"]


def test_noop_structured_returns_model_instance():
    class Sample(BaseModel):
        a: int = 0

    llm = NoopLLM()
    assert isinstance(llm.structured("hi", Sample), Sample)


# --------------------------------------------------------------------------- #
# Embeddings + vector store (RAG layer)
# --------------------------------------------------------------------------- #
def test_noop_embeddings_are_deterministic_and_sized():
    embeddings = NoopEmbeddings()
    assert embeddings.embed_query("hello") == embeddings.embed_query("hello")
    assert len(embeddings.embed_query("hello")) == NOOP_DIMENSIONS
    docs = embeddings.embed_documents(["a", "b"])
    assert len(docs) == 2 and all(len(v) == NOOP_DIMENSIONS for v in docs)


def test_memory_store_add_has_and_ranks_by_similarity():
    store = MemoryVectorStore()
    assert store.has_video("v1") is False

    chunks = ["alpha", "beta", "gamma"]
    embeddings = [[1.0, 0.0], [0.0, 1.0], [0.9, 0.1]]
    store.add_video("v1", chunks, embeddings)

    assert store.has_video("v1") is True
    # Query closest to [1,0] should surface "alpha" then "gamma".
    results = store.similarity_search("v1", [1.0, 0.0], k=2)
    assert results == ["alpha", "gamma"]


def test_memory_store_is_scoped_per_video():
    store = MemoryVectorStore()
    store.add_video("v1", ["only-v1"], [[1.0, 0.0]])
    assert store.similarity_search("v2", [1.0, 0.0], k=3) == []
