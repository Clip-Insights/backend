from typing import Protocol


class AnalyticsFetcher(Protocol):
    def fetch_and_store(self) -> None: ...
