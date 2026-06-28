from typing import Protocol


class VectorStoreProvider(Protocol):
    """A per-video store of transcript chunks and their embeddings.

    Chunks are grouped by `youtube_url` so retrieval only ever searches within
    the video being asked about.
    """

    def has_video(self, youtube_url: str) -> bool:
        """True if this video's chunks are already stored (skip re-embedding)."""
        ...

    def add_video(
        self, youtube_url: str, chunks: list[str], embeddings: list[list[float]]
    ) -> None:
        """Replace any stored chunks for the video with these chunk/embedding pairs."""
        ...

    def similarity_search(
        self, youtube_url: str, query_embedding: list[float], k: int
    ) -> list[str]:
        """Return the `k` most similar chunk texts for the video."""
        ...
