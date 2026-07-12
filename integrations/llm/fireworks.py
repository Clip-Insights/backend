"""Fireworks AI LLM provider (OpenAI-compatible API)."""

import os
from typing import TypeVar

import instructor
from pydantic import BaseModel

from integrations.fireworks import fireworks_key_manager, openai_client

# Llama 3.x serverless IDs were retired; gpt-oss-20b is a cheap serverless
# model that handles Clip Insights summary + RAG chat well enough.
LLM_MODEL = os.getenv("LLM_MODEL", "accounts/fireworks/models/deepseek-v4-flash")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))
LLM_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "8000"))

T = TypeVar("T", bound=BaseModel)


class FireworksLLM:
    def __init__(self):
        self._key_manager = fireworks_key_manager()

    def _client(self):
        return openai_client(self._key_manager.get_next_key())

    def _chat_kwargs(self, *, temperature: float | None):
        temp = temperature if temperature is not None else LLM_TEMPERATURE
        return {
            "model": LLM_MODEL,
            "temperature": temp,
            "max_tokens": LLM_MAX_OUTPUT_TOKENS,
        }

    def complete(self, prompt: str, *, temperature: float | None = None) -> str:
        response = self._client().chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            **self._chat_kwargs(temperature=temperature),
        )
        return response.choices[0].message.content or ""

    def stream(self, prompt: str, *, temperature: float | None = None):
        stream = self._client().chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            **self._chat_kwargs(temperature=temperature),
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta

    def chat_stream(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        temperature: float | None = None,
    ):
        api_messages = []
        if system:
            api_messages.append({"role": "system", "content": system})
        for message in messages:
            role = "user" if message.get("role") == "user" else "assistant"
            api_messages.append({"role": role, "content": message.get("content", "")})
        stream = self._client().chat.completions.create(
            messages=api_messages,
            stream=True,
            **self._chat_kwargs(temperature=temperature),
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta

    def structured(
        self, prompt: str, response_model: type[T], *, temperature: float | None = None
    ) -> T:
        """Return a validated Pydantic object using instructor for structured output."""
        client = instructor.from_openai(self._client())
        return client.chat.completions.create(
            response_model=response_model,
            messages=[{"role": "user", "content": prompt}],
            **self._chat_kwargs(temperature=temperature),
        )
