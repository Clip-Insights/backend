"""Pytest bootstrap shared by the whole backend suite.

Sets safe provider defaults *before* Django/settings import so that nothing tries
to read real third-party credentials during collection. Individual tests still
patch `get_llm` etc. where they exercise that behaviour.
"""
import os

os.environ.setdefault("LLM_PROVIDER", "noop")
os.environ.setdefault("EMAIL_PROVIDER", "console")
os.environ.setdefault("ANALYTICS_PROVIDER", "noop")
os.environ.setdefault("EMBEDDING_PROVIDER", "noop")
os.environ.setdefault("VECTORSTORE_PROVIDER", "memory")
os.environ.setdefault("LLM_API_KEYS", "test-key")
os.environ.setdefault("PAYMENT_PROVIDER", "noop")
