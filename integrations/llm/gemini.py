import os
from typing import TypeVar

import google.generativeai as genai
import instructor
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from integrations.keys import APIKeyManager, load_api_keys

LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))
LLM_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "8000"))

T = TypeVar("T", bound=BaseModel)


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
        return response.content

    def stream(self, prompt: str, *, temperature: float | None = None):
        for chunk in self._client(streaming=True, temperature=temperature).stream(prompt):
            if chunk.content:
                yield chunk.content

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
