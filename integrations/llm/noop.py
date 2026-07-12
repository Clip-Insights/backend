from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class NoopLLM:
    def complete(self, prompt: str, *, temperature: float | None = None) -> str:
        return "[noop llm response]"

    def stream(self, prompt: str, *, temperature: float | None = None):
        yield "[noop llm response]"

    def chat_stream(self, messages, *, system: str | None = None, temperature: float | None = None):
        yield "[noop llm response]"

    def structured(self, prompt: str, response_model: type[T], *, temperature: float | None = None) -> T:
        return response_model.model_construct()
