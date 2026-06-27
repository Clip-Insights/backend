class _MemoryDoc:
    def __init__(self, page_content: str):
        self.page_content = page_content


class MemoryVectorStore:
    def __init__(self):
        self._docs: list[tuple[str, dict]] = []

    def add_texts(self, texts: list[str], metadatas: list[dict]) -> None:
        for text, meta in zip(texts, metadatas):
            self._docs.append((text, meta))

    def similarity_search(self, query: str, k: int, filter: dict | None = None):
        filtered = self._docs
        if filter:
            filtered = [
                (t, m) for t, m in self._docs
                if all(str(m.get(fk)) == str(fv) for fk, fv in filter.items())
            ]
        return [_MemoryDoc(t) for t, _ in filtered[:k]]
