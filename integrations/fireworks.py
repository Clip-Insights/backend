"""Shared Fireworks AI client helpers (OpenAI-compatible API on AMD GPUs)."""

import os

from openai import OpenAI

from integrations.keys import APIKeyManager, load_api_keys

FIREWORKS_BASE_URL = os.getenv(
    "FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1"
)


def load_fireworks_keys() -> list[str]:
    return load_api_keys("FIREWORKS_API_KEYS")


def fireworks_key_manager() -> APIKeyManager:
    return APIKeyManager(load_fireworks_keys())


def openai_client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=FIREWORKS_BASE_URL)
