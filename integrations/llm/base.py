from typing import Iterator, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMProvider(Protocol):
    def complete(self, prompt: str, *, temperature: float | None = None) -> str: ...
    def stream(self, prompt: str, *, temperature: float | None = None) -> Iterator[str]: ...
    def structured(self, prompt: str, response_model: type[T], *, temperature: float | None = None) -> T: ...
