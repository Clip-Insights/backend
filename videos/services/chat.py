import logging
from collections import deque

from langchain_text_splitters import RecursiveCharacterTextSplitter

from integrations.registry import get_llm, get_vectorstore
from videos.models import VideoTranscriptTimeSlice

logger = logging.getLogger(__name__)

chat_memory_enabled = True
chat_history: deque = deque(maxlen=4)

TEXT_SPLITTER = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=50)


def process_chat_embeddings(youtube_url: str, transcription: str, slice_time: int) -> bool:
    try:
        transcript_entry, _created = VideoTranscriptTimeSlice.objects.get_or_create(
            youtube_url=youtube_url,
            defaults={"slice_time": slice_time},
        )
        transcript_entry.increment_access_count()

        chunks = TEXT_SPLITTER.split_text(transcription)
        logger.info("Created %s chunks", len(chunks))
        if not chunks:
            logger.error("No chunks were created from the transcription!")
            return False

        metadatas = [
            {
                "youtube_url": youtube_url,
                "chunk_index": str(idx),
                "slice_time": str(slice_time),
            }
            for idx in range(len(chunks))
        ]

        get_vectorstore().add_texts(texts=chunks, metadatas=metadatas)
        logger.info("Embeddings stored successfully.")

        transcript_entry.slice_time = slice_time
        transcript_entry.save()
        return True
    except Exception as e:
        logger.error("Error during transcription and embedding storage: %s", e)
        raise


def build_chat_stream(youtube_url: str, user_query: str, transcription: str, slice_time: int):
    process_chat_embeddings(youtube_url, transcription, slice_time)

    relevant_docs = get_vectorstore().similarity_search(
        query=user_query, k=3, filter={"youtube_url": youtube_url}
    )

    if not relevant_docs:
        logger.info("No relevant documents found, using truncated transcription")
        context = transcription[:1000]
    else:
        context = "\n\n".join(doc.page_content for doc in relevant_docs)
        logger.info("Retrieved %s documents", len(relevant_docs))

    if chat_memory_enabled and chat_history:
        chat_context = "\n".join([
            f"{'User' if msg['role'] == 'user' else 'Assistant'}: {msg['content']}"
            for msg in chat_history[-4:]
        ])
        prompt = f"""You are a helpful AI assistant answering questions about a video. 
                    Previous conversation:
                    {chat_context}
                    
                    Based on this context and the video content below, provide a concise answer (50-60 words) 
                    to the user's latest question in english. Maintain conversation continuity while staying focused on the video content.
                    
                    Video Content: {context}
                    
                    User's Latest Question: {user_query}"""
    else:
        prompt = f"""Provide a concise answer to the user's question based on the video content. 
                    Ensure the response is contextually accurate and in English.
                    
                    User Query: {user_query}
                    Relevant Context: {context}"""

    for chunk in get_llm().stream(prompt):
        yield f"data: {chunk}\n\n"
    yield "data: [DONE]\n\n"
