import os
from collections import deque
from typing import List


class APIKeyManager:
    def __init__(self, api_keys: List[str]):
        if not api_keys:
            raise ValueError("At least one API key is required")
        self.api_keys = deque(api_keys)

    def get_next_key(self) -> str:
        current_key = self.api_keys[0]
        self.api_keys.rotate(-1)
        return current_key


def load_api_keys(env_var: str) -> List[str]:
    keys_str = os.getenv(env_var, "")
    if not keys_str:
        raise ValueError(f"{env_var} not found in environment variables")
    keys = [key.strip() for key in keys_str.split(",") if key.strip()]
    if not keys:
        raise ValueError(f"No valid API keys found in {env_var}")
    return keys
