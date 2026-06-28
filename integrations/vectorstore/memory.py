"""In-process vector store: cosine similarity in pure Python.

Used for tests and local runs without CockroachDB. Holds everything in a dict,
so it is not shared across processes and is cleared on restart.
"""
from math import sqrt


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sqrt(sum(x * x for x in a))
    norm_b = sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class MemoryVectorStore:
    def __init__(self) -> None:
        self._videos: dict[str, list[tuple[str, list[float]]]] = {}

    def has_video(self, youtube_url: str) -> bool:
        return bool(self._videos.get(youtube_url))

    def add_video(
        self, youtube_url: str, chunks: list[str], embeddings: list[list[float]]
    ) -> None:
        self._videos[youtube_url] = list(zip(chunks, embeddings))

    def similarity_search(
        self, youtube_url: str, query_embedding: list[float], k: int
    ) -> list[str]:
        entries = self._videos.get(youtube_url, [])
        ranked = sorted(
            entries, key=lambda entry: _cosine_similarity(query_embedding, entry[1]), reverse=True
        )
        return [content for content, _ in ranked[:k]]
