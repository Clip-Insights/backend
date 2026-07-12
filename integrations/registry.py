import importlib
import os
import threading

_PROVIDERS = {
    "llm": {
        "fireworks": "integrations.llm.fireworks.FireworksLLM",
        "gemini": "integrations.llm.gemini.GeminiLLM",
        "noop": "integrations.llm.noop.NoopLLM",
    },
    "transcription": {
        "groq": "integrations.transcription.groq_whisper.GroqWhisperTranscription",
    },
    "embedding": {
        "fireworks": "integrations.embeddings.fireworks.FireworksEmbeddings",
        "gemini": "integrations.embeddings.gemini.GeminiEmbeddings",
        "noop": "integrations.embeddings.noop.NoopEmbeddings",
    },
    "vectorstore": {
        "cockroach": "integrations.vectorstore.cockroach.CockroachVectorStore",
        "memory": "integrations.vectorstore.memory.MemoryVectorStore",
    },
    "storage": {
        "s3": "integrations.storage.s3.S3Storage",
    },
    "email": {
        "smtp": "integrations.email.smtp.SMTPEmailSender",
        "console": "integrations.email.console.ConsoleEmailSender",
        "resend": "integrations.email.resend.ResendEmailSender",
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
    return _get("llm", "LLM_PROVIDER", "fireworks")


def get_transcription():
    return _get("transcription", "TRANSCRIPTION_PROVIDER", "groq")


def get_embeddings():
    return _get("embedding", "EMBEDDING_PROVIDER", "fireworks")


def get_vectorstore():
    return _get("vectorstore", "VECTORSTORE_PROVIDER", "cockroach")


def get_storage():
    return _get("storage", "STORAGE_PROVIDER", "s3")


def get_email():
    return _get("email", "EMAIL_PROVIDER", "smtp")


def get_oauth():
    return _get("oauth", "OAUTH_PROVIDER", "google")


def get_analytics():
    return _get("analytics", "ANALYTICS_PROVIDER", "ga4")
