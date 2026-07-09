import json
import logging

from integrations.registry import get_embeddings, get_llm, get_vectorstore
from videos.prompts import CHAT_SYSTEM_PROMPT, build_chat_user_message
from videos.services.chunking import chunk_text

logger = logging.getLogger(__name__)

# How many recent messages of history to carry into the prompt.
CHAT_MEMORY_WINDOW = 3
# How many transcript chunks to retrieve and feed the model per question.
RETRIEVAL_K = 3
# Below this length the "transcript" is almost certainly an error sentinel
# (e.g. "Transcript not available"), so don't embed/store it.
MIN_TRANSCRIPT_CHARS = 40
# Bounded fallback context used only when retrieval itself fails.
FALLBACK_CONTEXT_CHARS = 4000


def _history_messages(chat_history: list[dict] | None) -> list[dict]:
    """Normalise client history into role/content dicts, keeping the recent window."""
    messages = []
    for message in (chat_history or [])[-CHAT_MEMORY_WINDOW:]:
        content = (message.get("content") or "").strip()
        if not content:
            continue
        role = "user" if message.get("role") == "user" else "assistant"
        messages.append({"role": role, "content": content})
    return messages


def _store_key(embeddings, youtube_url: str) -> str:
    """Vectors are only comparable within one embedding model, so the storage
    key carries the model identity — switching models re-embeds instead of
    silently searching against stale vectors."""
    return f"{getattr(embeddings, 'model_id', 'default')}::{youtube_url}"


def _retrieve_context(youtube_url: str, transcription: str, user_query: str) -> str | None:
    """Embed the transcript (once per video) and return the top-K chunks for the query.

    Returns None if there is nothing usable to retrieve from or if the vector
    store/embeddings fail — the caller then falls back to the raw transcript so
    chat never breaks.
    """
    if not transcription or len(transcription.strip()) < MIN_TRANSCRIPT_CHARS:
        return None
    try:
        store = get_vectorstore()
        embeddings = get_embeddings()
        key = _store_key(embeddings, youtube_url)

        if not store.has_video(key):
            chunks = chunk_text(transcription)
            if not chunks:
                return None
            store.add_video(key, chunks, embeddings.embed_documents(chunks))

        query_vector = embeddings.embed_query(user_query)
        documents = store.similarity_search(key, query_vector, RETRIEVAL_K)
        return "\n\n".join(documents) if documents else None
    except Exception as exc:
        logger.warning("Vector retrieval failed (%s); falling back to transcript", exc)
        return None


def build_chat_stream(youtube_url: str, user_query: str, transcription: str, chat_history: list[dict] | None = None):
    """Stream a conversational answer to `user_query` as SSE events.

    The static system prompt carries persona/behaviour; the retrieved transcript
    excerpts ride inside the final user message (context changes per turn, so
    keeping it out of the system prompt preserves provider prompt caching);
    recent history is passed as real chat turns. Each token is JSON-encoded so
    newlines survive the `data: ...\\n\\n` SSE framing.
    """
    context = _retrieve_context(youtube_url, transcription, user_query)
    if context is None and transcription:
        context = transcription[:FALLBACK_CONTEXT_CHARS]

    messages = _history_messages(chat_history)
    messages.append({"role": "user", "content": build_chat_user_message(context=context or "", query=user_query)})

    for chunk in get_llm().chat_stream(messages, system=CHAT_SYSTEM_PROMPT):
        yield f"data: {json.dumps(chunk)}\n\n"
    yield "data: [DONE]\n\n"
