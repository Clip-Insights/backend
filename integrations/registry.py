import importlib
import logging
import os
import threading

logger = logging.getLogger(__name__)

_PROVIDERS = {
    "llm": {
        "gemini": "integrations.llm.gemini.GeminiLLM",
        "noop": "integrations.llm.noop.NoopLLM",
    },
    "transcription": {
        "groq": "integrations.transcription.groq_whisper.GroqWhisperTranscription",
    },
    "embedding": {
        "huggingface": "integrations.embeddings.huggingface.HuggingFaceEmbeddingsProvider",
    },
    "vectorstore": {
        "cockroach": "integrations.vectorstore.cockroach.CockroachVectorStoreProvider",
        "memory": "integrations.vectorstore.memory.MemoryVectorStore",
    },
    "storage": {
        "s3": "integrations.storage.s3.S3Storage",
    },
    "email": {
        "smtp": "integrations.email.smtp.SMTPEmailSender",
        "console": "integrations.email.console.ConsoleEmailSender",
    },
    "oauth": {
        "google": "integrations.oauth.google.GoogleOAuthVerifier",
    },
    "analytics": {
        "ga4": "integrations.analytics.ga4.GA4AnalyticsFetcher",
        "noop": "integrations.analytics.noop.NoopAnalyticsFetcher",
    },
}

_singletons: dict = {}
_lock = threading.Lock()

LLM_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "8000"))


def _import_class(dotted: str):
    module_path, class_name = dotted.rsplit(".", 1)
    return getattr(importlib.import_module(module_path), class_name)


def _get(kind: str, env_var: str, default: str):
    provider = os.getenv(env_var, default).lower()
    options = _PROVIDERS[kind]
    if provider not in options:
        raise ValueError(f"Unknown {env_var}={provider!r}. Valid: {list(options)}")
    key = f"{kind}:{provider}"
    if key not in _singletons:
        with _lock:
            if key not in _singletons:
                _singletons[key] = _import_class(options[provider])()
    return _singletons[key]


def get_llm():
    return _get("llm", "LLM_PROVIDER", "gemini")


def get_transcription():
    return _get("transcription", "TRANSCRIPTION_PROVIDER", "groq")


def get_embeddings():
    _maybe_warmup()
    return _get("embedding", "EMBEDDING_PROVIDER", "huggingface")


def get_vectorstore():
    _maybe_warmup()
    return _get("vectorstore", "VECTORSTORE_PROVIDER", "cockroach")


def get_storage():
    return _get("storage", "STORAGE_PROVIDER", "s3")


def get_email():
    return _get("email", "EMAIL_PROVIDER", "smtp")


def get_oauth():
    return _get("oauth", "OAUTH_PROVIDER", "google")


def get_analytics():
    return _get("analytics", "ANALYTICS_PROVIDER", "ga4")


class _LazyProxy:
    """ponytail: thread-safe lazy delegate for expensive vectorstore/embeddings."""

    def __init__(self, factory):
        self._factory = factory
        self._delegate = None
        self._lock = threading.Lock()

    def _resolve(self):
        if self._delegate is not None:
            return self._delegate
        with self._lock:
            if self._delegate is None:
                self._delegate = self._factory()
        return self._delegate

    def __getattr__(self, name):
        return getattr(self._resolve(), name)


def _background_warmup():
    import time
    time.sleep(1)
    try:
        get_embeddings()
        get_vectorstore()
        logger.info("Background warm-up complete")
    except Exception as e:
        logger.warning("Background warm-up failed: %s", e)


_warmup_started = False


def _maybe_warmup():
    global _warmup_started
    if _warmup_started or os.getenv("VECTORSTORE_PROVIDER", "cockroach") != "cockroach":
        return
    _warmup_started = True
    threading.Thread(target=_background_warmup, daemon=True).start()
