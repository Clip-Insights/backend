from integrations.embeddings.huggingface import HuggingFaceEmbeddingsProvider
from integrations.vectorstore.cockroach_store import CockroachVectorStore, CONNECTION_STRING


class CockroachVectorStoreProvider:
    def __init__(self, embeddings=None, collection_name: str = "video_transcripts"):
        if embeddings is None:
            embeddings = HuggingFaceEmbeddingsProvider()
        self._store = CockroachVectorStore(
            embeddings=embeddings.langchain_model,
            collection_name=collection_name,
            connection=CONNECTION_STRING,
            use_jsonb=True,
        )

    def add_texts(self, texts: list[str], metadatas: list[dict]) -> None:
        self._store.add_texts(texts=texts, metadatas=metadatas)

    def similarity_search(self, query: str, k: int, filter: dict | None = None):
        return self._store.similarity_search(query=query, k=k, filter=filter)
