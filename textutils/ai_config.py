"""
AI Configuration Module
Unified configuration for LLM and vector embeddings using LangChain.
Manages Gemini LLM, embeddings, text splitting, and PGVector storage.
"""

import os
import threading
from collections import deque
from typing import List, Optional
from dotenv import load_dotenv
import logging
logger = logging.getLogger(__name__)

# NOTE: langchain_huggingface is intentionally NOT imported here at module level.
# It transitively imports torch + sentence-transformers which takes 5-10 seconds.
# That import is deferred into get_embedding_model() and triggered lazily on first use.
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from utils.cockroachdb_vectorstore import CockroachVectorStore

# Load environment variables
load_dotenv()

# Configuration Constants - Updated for pre-baked models
EMBEDDINGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'embeddings')
CHUNK_SIZE = 800
CHUNK_OVERLAP = 50
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))
LLM_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "8000"))

# Database Configuration for PGVector
DB_NAME = os.getenv("DATABASE_NAME", "clipinsights")
DB_USER = os.getenv("DATABASE_USER", "postgres")
DB_PASSWORD = os.getenv("DATABASE_PASSWORD", "root")
DB_HOST = os.getenv("DATABASE_HOST", "localhost")
DB_PORT = os.getenv("DATABASE_PORT", "5432")
DB_CERT_PATH = os.getenv("DATABASE_CERT_PATH", "/root/.postgresql/root.crt")

CONNECTION_STRING = f"cockroachdb+psycopg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?sslmode=verify-full&sslrootcert={DB_CERT_PATH}"


class APIKeyManager:
    """Manages API key rotation to distribute load and avoid rate limits."""

    def __init__(self, api_keys: List[str]):
        if not api_keys:
            raise ValueError("At least one API key is required")
        self.api_keys = deque(api_keys)

    def get_next_key(self) -> str:
        """Get the next API key in rotation."""
        current_key = self.api_keys[0]
        self.api_keys.rotate(-1)
        return current_key


def _load_api_keys() -> List[str]:
    """Load and parse comma-separated API keys from LLM_API_KEYS environment variable."""
    keys_str = os.getenv("LLM_API_KEYS", "")
    if not keys_str:
        raise ValueError("LLM_API_KEYS not found in environment variables")

    keys = [key.strip() for key in keys_str.split(',') if key.strip()]
    if not keys:
        raise ValueError("No valid API keys found in LLM_API_KEYS")

    return keys


# Initialize API key manager (fast — no I/O beyond env var read)
try:
    api_keys = _load_api_keys()
    key_manager = APIKeyManager(api_keys)
    logger.info(f"✓ Initialized API key manager with {len(api_keys)} keys")
except Exception as e:
    logger.error(f"✗ Failed to initialize API key manager: {e}")
    key_manager = None


def get_llm(streaming: bool = True, temperature: Optional[float] = None) -> ChatGoogleGenerativeAI:
    """
    Get LangChain LLM instance with automatic key rotation.

    Args:
        streaming: Enable streaming responses (default: True)
        temperature: Model temperature, overrides default if provided

    Returns:
        ChatGoogleGenerativeAI instance configured with Gemini
    """
    if not key_manager:
        raise RuntimeError("API key manager not initialized. Check LLM_API_KEYS in .env file")

    api_key = key_manager.get_next_key()
    logger.info(f"Using API Key: {api_key[:15]}****")
    temp = temperature if temperature is not None else LLM_TEMPERATURE

    return ChatGoogleGenerativeAI(
        model=LLM_MODEL,
        google_api_key=api_key,
        temperature=temp,
        streaming=streaming,
        max_output_tokens=LLM_MAX_OUTPUT_TOKENS
    )


def get_embedding_model(model_name: str = 'all-MiniLM-L6-v2'):
    """
    Get pre-baked HuggingFace embedding model.
    Optimized for Cloud Run - assumes model is pre-baked into container.

    The HuggingFaceEmbeddings import is intentionally deferred here so that
    torch/sentence-transformers are not loaded at Django startup time.

    Args:
        model_name: Name of the HuggingFace model (default: all-MiniLM-L6-v2)

    Returns:
        HuggingFaceEmbeddings instance
    """
    from langchain_huggingface import HuggingFaceEmbeddings  # deferred — triggers torch import

    model_path = os.path.join(EMBEDDINGS_DIR, model_name)

    if os.path.exists(model_path):
        logger.info(f"✓ Loading pre-baked embeddings from: {model_path}")
        return HuggingFaceEmbeddings(model_name=model_path)
    else:
        # Fallback: Try loading from HuggingFace cache (also pre-baked)
        cache_path = os.path.expanduser("~/.cache/huggingface")
        if os.path.exists(cache_path):
            logger.info(f"✓ Loading from HuggingFace cache: {cache_path}")
            return HuggingFaceEmbeddings(model_name=model_name)
        else:
            # Last resort: Download at runtime (should not happen in production)
            logger.warning(f"⚠️ Model not found at {model_path}, downloading...")
            os.makedirs(EMBEDDINGS_DIR, exist_ok=True)
            embeddings = HuggingFaceEmbeddings(model_name=model_name)
            embeddings._client.save_pretrained(model_path)
            return embeddings


def get_text_splitter() -> RecursiveCharacterTextSplitter:
    """
    Get configured text splitter for chunking documents.

    Returns:
        RecursiveCharacterTextSplitter configured with chunk size and overlap
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP
    )


def get_vector_store(
    collection_name: str = "video_transcripts",
    embedding_model=None
) -> CockroachVectorStore:
    """
    Get or create PGVector store for embeddings.

    Args:
        collection_name: Name of the vector collection/table
        embedding_model: Embedding model to use (creates default if None)

    Returns:
        PGVector store instance
    """
    if embedding_model is None:
        embedding_model = get_embedding_model()

    try:
        vectorstore = CockroachVectorStore(
            embeddings=embedding_model,
            collection_name=collection_name,
            connection=CONNECTION_STRING,
            use_jsonb=True,
        )
        logger.info(f"✓ CockroachVector store initialized: {collection_name}")
        return vectorstore
    except Exception as e:
        logger.info(f"✗ Failed to initialize CockroachVector store: {e}")
        raise


# ---------------------------------------------------------------------------
# Lazy proxy — enables transparent on-demand initialization of heavy objects.
# `from .ai_config import VECTOR_STORE` imports this proxy object; attribute
# access on it (e.g. VECTOR_STORE.add_texts) triggers initialization exactly
# once, then delegates every call to the real object. Thread-safe.
# ---------------------------------------------------------------------------
class _LazyInitializer:
    def __init__(self, factory):
        object.__setattr__(self, '_factory', factory)
        object.__setattr__(self, '_delegate', None)
        object.__setattr__(self, '_lock', threading.Lock())

    def _initialize(self):
        delegate = object.__getattribute__(self, '_delegate')
        if delegate is not None:
            return delegate
        lock = object.__getattribute__(self, '_lock')
        with lock:
            delegate = object.__getattribute__(self, '_delegate')
            if delegate is None:
                factory = object.__getattribute__(self, '_factory')
                delegate = factory()
                object.__setattr__(self, '_delegate', delegate)
        return delegate

    def __getattr__(self, name):
        return getattr(self._initialize(), name)

    def __bool__(self):
        # The proxy itself is always truthy (it is not None)
        return True

    def __repr__(self):
        delegate = object.__getattribute__(self, '_delegate')
        return repr(delegate) if delegate is not None else '<LazyInitializer: pending>'


# Cached embedding model singleton shared by EMBEDDING_MODEL and VECTOR_STORE
_embedding_model_instance = None
_embedding_model_lock = threading.Lock()


def _get_cached_embedding_model():
    """Returns the shared embedding model, loading it exactly once."""
    global _embedding_model_instance
    if _embedding_model_instance is None:
        with _embedding_model_lock:
            if _embedding_model_instance is None:
                logger.info("Lazy-loading embedding model (first use)...")
                _embedding_model_instance = get_embedding_model()
                logger.info("✓ Embedding model ready")
    return _embedding_model_instance


# TEXT_SPLITTER is trivially cheap (no I/O, no ML) — keep eager.
TEXT_SPLITTER = get_text_splitter()

# EMBEDDING_MODEL and VECTOR_STORE are expensive — initialize lazily on first use.
EMBEDDING_MODEL = _LazyInitializer(_get_cached_embedding_model)
VECTOR_STORE = _LazyInitializer(
    lambda: get_vector_store(embedding_model=_get_cached_embedding_model())
)


# ---------------------------------------------------------------------------
# Background warm-up: begin loading AI components immediately after the server
# starts, but in a daemon thread so it does NOT block Uvicorn from listening.
# By the time real traffic arrives (Cloud Run routes after health check passes),
# the components will usually be fully initialized.
# ---------------------------------------------------------------------------
def _background_warmup():
    import time
    time.sleep(1)  # Let Uvicorn finish binding to the port first
    try:
        logger.info("Background warm-up: loading AI components...")
        _get_cached_embedding_model()
        get_vector_store(embedding_model=_embedding_model_instance)
        logger.info("✓ Background warm-up complete — AI components ready")
    except Exception as e:
        logger.warning(f"Background warm-up failed (will retry on first request): {e}")


_warmup_thread = threading.Thread(target=_background_warmup, daemon=True)
_warmup_thread.start()


__all__ = [
    'get_llm',
    'get_embedding_model',
    'get_text_splitter',
    'get_vector_store',
    'EMBEDDING_MODEL',
    'TEXT_SPLITTER',
    'VECTOR_STORE',
    'CONNECTION_STRING',
    'LLM_MAX_OUTPUT_TOKENS',
]
