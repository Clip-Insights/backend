"""
AI Configuration Module
Unified configuration for LLM and vector embeddings using LangChain.
Manages Gemini LLM, embeddings, text splitting, and PGVector storage.
"""

import os
from collections import deque
from typing import List, Optional
from dotenv import load_dotenv
import logging
logger = logging.getLogger(__name__)

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_huggingface import HuggingFaceEmbeddings
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


# Initialize API key manager
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


def get_embedding_model(model_name: str = 'all-MiniLM-L6-v2') -> HuggingFaceEmbeddings:
    """
    Get pre-baked HuggingFace embedding model.
    Optimized for Cloud Run - assumes model is pre-baked into container.
    
    Args:
        model_name: Name of the HuggingFace model (default: all-MiniLM-L6-v2)
        
    Returns:
        HuggingFaceEmbeddings instance
    """
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
    embedding_model: Optional[HuggingFaceEmbeddings] = None
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


# Initialize global instances
logger.info("Initializing AI components...")
EMBEDDING_MODEL = get_embedding_model()
TEXT_SPLITTER = get_text_splitter()

try:
    VECTOR_STORE = get_vector_store(embedding_model=EMBEDDING_MODEL)
    logger.info("✓ All AI components initialized successfully")
except Exception as e:
    logger.error(f"✗ Warning: PGVector store initialization failed: {e}")
    VECTOR_STORE = None


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
