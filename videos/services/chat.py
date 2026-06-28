import logging

from integrations.registry import get_embeddings, get_llm, get_vectorstore
from videos.prompts import build_chat_prompt
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


def _format_history(chat_history: list[dict]) -> str:
    lines = []
    for message in (chat_history or [])[-CHAT_MEMORY_WINDOW:]:
        role = "User" if message.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {message.get('content', '')}")
    return "\n".join(lines)


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

        if not store.has_video(youtube_url):
            chunks = chunk_text(transcription)
            if not chunks:
                return None
            store.add_video(youtube_url, chunks, embeddings.embed_documents(chunks))

        query_vector = embeddings.embed_query(user_query)
        documents = store.similarity_search(youtube_url, query_vector, RETRIEVAL_K)
        return "\n\n".join(documents) if documents else None
    except Exception as exc:
        logger.warning("Vector retrieval failed (%s); falling back to transcript", exc)
        return None


def build_chat_stream(youtube_url: str, user_query: str, transcription: str, chat_history: list[dict] | None = None):
    """Stream a conversational answer to `user_query`.

    Only the transcript chunks most relevant to the question are sent to the
    model (retrieved from the vector store), together with the recent chat
    history. If retrieval is unavailable, a bounded slice of the transcript is
    used so the user still gets an answer.
    """
    context = _retrieve_context(youtube_url, transcription, user_query)
    if context is None and transcription:
        context = transcription[:FALLBACK_CONTEXT_CHARS]

    prompt = build_chat_prompt(
        history=_format_history(chat_history or []),
        context=context or "",
        query=user_query,
    )

    for chunk in get_llm().stream(prompt):
        yield f"data: {chunk}\n\n"
    yield "data: [DONE]\n\n"
