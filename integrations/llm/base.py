from typing import Iterator, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMProvider(Protocol):
    def complete(self, prompt: str, *, temperature: float | None = None) -> str: ...
    def stream(self, prompt: str, *, temperature: float | None = None) -> Iterator[str]: ...
    def structured(self, prompt: str, response_model: type[T], *, temperature: float | None = None) -> T: ...

    def chat_stream(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        temperature: float | None = None,
    ) -> Iterator[str]:
        """Stream a reply to a conversation.

        `messages` are `{"role": "user"|"assistant", "content": str}` dicts in
        chronological order; `system` is a stable system prompt sent separately
        so providers can apply role-aware handling (and prompt caching).
        """
        ...
