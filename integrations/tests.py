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


def test_registry_resolves_fireworks_providers(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fireworks")
    monkeypatch.setenv("FIREWORKS_API_KEYS", "fw-test-key")
    registry._singletons.clear()
    from integrations.embeddings.fireworks import FireworksEmbeddings
    from integrations.llm.fireworks import FireworksLLM

    llm = registry.get_llm()
    embeddings = registry.get_embeddings()
    assert isinstance(llm, FireworksLLM)
    assert isinstance(embeddings, FireworksEmbeddings)
    assert embeddings.model_id  # env-driven; used as RAG store key prefix
    assert registry.get_llm() is llm
    assert registry.get_embeddings() is embeddings


def test_registry_resolves_gemini_embeddings(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_API_KEYS", "gemini-test-key")
    registry._singletons.clear()
    from integrations.embeddings.gemini import GeminiEmbeddings

    embeddings = registry.get_embeddings()
    assert isinstance(embeddings, GeminiEmbeddings)
    assert embeddings.model_id
    assert registry.get_embeddings() is embeddings


def test_fireworks_embeddings_nomic_prefixes(monkeypatch):
    monkeypatch.setenv("FIREWORKS_API_KEYS", "fw-test-key")
    import integrations.embeddings.fireworks as fw_emb

    captured = {}

    class FakeEmbedding:
        def __init__(self, embedding, index):
            self.embedding = embedding
            self.index = index

    class FakeResponse:
        def __init__(self, data):
            self.data = data

    class FakeEmbeddingsAPI:
        def create(self, **kwargs):
            captured["kwargs"] = kwargs
            inputs = kwargs["input"]
            return FakeResponse(
                [FakeEmbedding([float(i), 0.0], i) for i in range(len(inputs))]
            )

    class FakeClient:
        embeddings = FakeEmbeddingsAPI()

    monkeypatch.setattr(fw_emb, "openai_client", lambda _key: FakeClient())
    embeddings = fw_emb.FireworksEmbeddings()
    embeddings.model_id = "nomic-ai/nomic-embed-text-v1.5"
    docs = embeddings.embed_documents(["alpha", "beta"])
    assert captured["kwargs"]["input"] == [
        "search_document: alpha",
        "search_document: beta",
    ]
    assert len(docs) == 2
    embeddings.embed_query("hello")
    assert captured["kwargs"]["input"] == ["search_query: hello"]


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
