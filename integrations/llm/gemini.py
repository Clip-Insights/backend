import os
from typing import TypeVar

import google.generativeai as genai
import instructor
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from integrations.keys import APIKeyManager, load_api_keys

# gemini-2.5-flash is retiring; Gemini 3 Flash is the replacement. The stable
# `gemini-3.5-flash` also works but is frequently capacity-throttled (503) on
# free-tier keys, so the reliably-served Gemini 3 Flash id is the default.
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3-flash-preview")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))
LLM_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "8000"))

T = TypeVar("T", bound=BaseModel)


def _text_of(message) -> str:
    """Plain text of a LangChain message/chunk.

    Gemini 3 models return `content` as a list of typed blocks (text, thinking,
    signatures...) instead of a string; only the text blocks are user-facing.
    """
    content = message.content
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


class GeminiLLM:
    def __init__(self):
        self._key_manager = APIKeyManager(load_api_keys("LLM_API_KEYS"))

    def _client(self, *, streaming: bool, temperature: float | None) -> ChatGoogleGenerativeAI:
        temp = temperature if temperature is not None else LLM_TEMPERATURE
        return ChatGoogleGenerativeAI(
            model=LLM_MODEL,
            google_api_key=self._key_manager.get_next_key(),
            temperature=temp,
            streaming=streaming,
            max_output_tokens=LLM_MAX_OUTPUT_TOKENS,
        )

    def complete(self, prompt: str, *, temperature: float | None = None) -> str:
        response = self._client(streaming=False, temperature=temperature).invoke(prompt)
        return _text_of(response)

    def stream(self, prompt: str, *, temperature: float | None = None):
        for chunk in self._client(streaming=True, temperature=temperature).stream(prompt):
            text = _text_of(chunk)
            if text:
                yield text

    def chat_stream(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        temperature: float | None = None,
    ):
        lc_messages = []
        if system:
            lc_messages.append(SystemMessage(content=system))
        for message in messages:
            role_cls = HumanMessage if message.get("role") == "user" else AIMessage
            lc_messages.append(role_cls(content=message.get("content", "")))
        for chunk in self._client(streaming=True, temperature=temperature).stream(lc_messages):
            text = _text_of(chunk)
            if text:
                yield text

    def structured(self, prompt: str, response_model: type[T], *, temperature: float | None = None) -> T:
        """Return a validated Pydantic object using instructor for structured output.

        Instructor constrains Gemini to the `response_model` schema and parses the
        reply into it, so no manual JSON/regex handling is needed downstream.
        """
        temp = temperature if temperature is not None else LLM_TEMPERATURE
        genai.configure(api_key=self._key_manager.get_next_key())
        client = instructor.from_gemini(
            client=genai.GenerativeModel(
                model_name=LLM_MODEL,
                generation_config={"temperature": temp, "max_output_tokens": LLM_MAX_OUTPUT_TOKENS},
            ),
            mode=instructor.Mode.GEMINI_JSON,
        )
        return client.chat.completions.create(
            response_model=response_model,
            messages=[{"role": "user", "content": prompt}],
        )
