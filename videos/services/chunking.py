"""Split a transcript into overlapping character windows for embedding.

A small, dependency-free splitter (≈800 chars, 50 overlap) that mirrors the
sizing the project used before. Overlap keeps a sentence that straddles a
boundary retrievable from either chunk.
"""

CHUNK_SIZE = 800
CHUNK_OVERLAP = 50


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    step = max(1, size - overlap)
    chunks: list[str] = []
    for start in range(0, len(text), step):
        chunk = text[start : start + size].strip()
        if chunk:
            chunks.append(chunk)
        if start + size >= len(text):
            break
    return chunks
