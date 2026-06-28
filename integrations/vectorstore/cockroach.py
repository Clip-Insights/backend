"""CockroachDB-backed vector store using its pgvector-compatible VECTOR type.

Chunks live in a single table keyed by `youtube_url`. We reuse Django's
configured database connection (no separate connection string or SQLAlchemy),
so this store always talks to the same CockroachDB the rest of the app uses.

Requires CockroachDB v25.1+ (pgvector compatibility). The chat service wraps all
calls in a try/except and falls back to the raw transcript, so an older cluster
degrades gracefully instead of breaking chat.
"""
from django.db import connection

TABLE = "video_transcript_chunks"


def _to_vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


class CockroachVectorStore:
    def _ensure_table(self, dimensions: int) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    youtube_url STRING NOT NULL,
                    chunk_index INT NOT NULL,
                    content STRING NOT NULL,
                    embedding VECTOR({dimensions}) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE (youtube_url, chunk_index)
                )
                """
            )
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS {TABLE}_url_idx ON {TABLE} (youtube_url)"
            )

    def has_video(self, youtube_url: str) -> bool:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT 1 FROM {TABLE} WHERE youtube_url = %s LIMIT 1", [youtube_url]
                )
                return cursor.fetchone() is not None
        except Exception:
            # Table not created yet (first ever ingest): treat as "not stored".
            return False

    def add_video(
        self, youtube_url: str, chunks: list[str], embeddings: list[list[float]]
    ) -> None:
        if not chunks or not embeddings:
            return
        self._ensure_table(len(embeddings[0]))
        with connection.cursor() as cursor:
            # Idempotent re-ingest: drop any stale chunks for this video first.
            cursor.execute(f"DELETE FROM {TABLE} WHERE youtube_url = %s", [youtube_url])
            # Insert one row at a time — CockroachDB advises against batching VECTOR inserts.
            for index, (content, embedding) in enumerate(zip(chunks, embeddings)):
                cursor.execute(
                    f"""
                    INSERT INTO {TABLE} (youtube_url, chunk_index, content, embedding)
                    VALUES (%s, %s, %s, %s::VECTOR)
                    """,
                    [youtube_url, index, content, _to_vector_literal(embedding)],
                )

    def similarity_search(
        self, youtube_url: str, query_embedding: list[float], k: int
    ) -> list[str]:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT content FROM {TABLE}
                WHERE youtube_url = %s
                ORDER BY embedding <=> %s::VECTOR
                LIMIT %s
                """,
                [youtube_url, _to_vector_literal(query_embedding), k],
            )
            return [row[0] for row in cursor.fetchall()]
