# views.py
import os
import logging
import traceback
import json
from django.http import JsonResponse, StreamingHttpResponse
from django.utils.timezone import now
from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from collections import deque
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field
from typing import List
import time
import yt_dlp
from uuid import uuid4
import re
from groq import Groq
from dotenv import load_dotenv

from .models import VideoResource, VideoTranscriptTimeSlice, VideoTranscripts
from .ai_config import (
    get_llm,
    TEXT_SPLITTER,
    VECTOR_STORE,
    LLM_MAX_OUTPUT_TOKENS
)

logger = logging.getLogger(__name__)
from .utils import parse_keypoints, robust_json_parser, fix_pydantic_validation
from .serializers import ChatInputSerializer, SummaryInputSerializer, TranscribeInputSerializer

load_dotenv()

logger = logging.getLogger(__name__)

caching = True
chat_memory_enabled = True
chat_history = deque(maxlen=4)

# Groq key rotation for transcription
_groq_keys = None
_groq_key_index = 0

def _get_groq_client():
    """Get Groq client with key rotation for audio transcription."""
    global _groq_keys, _groq_key_index
    
    if _groq_keys is None:
        keys_str = os.getenv("GROQ_API_KEYS", "")
        if not keys_str:
            raise ValueError("GROQ_API_KEYS not found in .env file")
        _groq_keys = [k.strip() for k in keys_str.split(',') if k.strip()]
    
    if not _groq_keys:
        raise ValueError("No valid Groq API keys found")
    
    key = _groq_keys[_groq_key_index]
    _groq_key_index = (_groq_key_index + 1) % len(_groq_keys)
    return Groq(api_key=key)

class ChatView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = ChatInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        validated_data = serializer.validated_data

        youtube_url = validated_data.get('youtube_url')
        user_query = validated_data.get('query')
        transcription = validated_data.get('transcription')
        slice_time = validated_data.get('slice_time', -1)
        stream_mode = validated_data.get('stream', False)

        if not youtube_url or not user_query:
            return Response(
                {
                    'youtube_url': ['This field is required.'],
                    'query': ['This field is required.']
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        def process_transcription_and_store_embeddings():
            try:
                transcript_entry, created = VideoTranscriptTimeSlice.objects.get_or_create(
                    youtube_url=youtube_url,
                    defaults={"slice_time": slice_time}
                )
                transcript_entry.increment_access_count()
                
                # Create chunks from transcription
                chunks = TEXT_SPLITTER.split_text(transcription)
                logger.info(f"Created {len(chunks)} chunks")
                
                if len(chunks) == 0:
                    logger.error("Warning: No chunks were created from the transcription!")
                    return False
                
                # Prepare metadata for each chunk
                metadatas = [
                    {
                        "youtube_url": youtube_url,
                        "chunk_index": str(idx),
                        "slice_time": str(slice_time),
                    }
                    for idx in range(len(chunks))
                ]
                
                # Store embeddings in PGVector
                VECTOR_STORE.add_texts(
                    texts=chunks,
                    metadatas=metadatas
                )
                logger.info("Embeddings stored successfully in PGVector.")

                transcript_entry.slice_time = slice_time
                transcript_entry.save()
                return True

            except Exception as e:
                logger.error(f"Error during transcription and embedding storage: {e}")
                raise
            
        def generate_streaming_response():
            try:
                process_transcription_and_store_embeddings()
                
                # Retrieve relevant documents using similarity search
                relevant_docs = VECTOR_STORE.similarity_search(
                    query=user_query,
                    k=3,
                    filter={"youtube_url": youtube_url}
                )
                
                if not relevant_docs:
                    logger.info("No relevant documents found, using truncated transcription")
                    context = transcription[:1000]
                else:
                    context = "\n\n".join(doc.page_content for doc in relevant_docs)
                    logger.info(f"Retrieved {len(relevant_docs)} documents, context length: {len(context)} characters")
                
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

                llm = get_llm()
                for chunk in llm.stream(prompt):
                    if chunk.content:
                        yield f"data: {chunk.content}\n\n"

                yield "data: [DONE]\n\n"

            except Exception as e:
                logger.error(f"Error during chat streaming: {e}")
                yield f"data: Something went wrong\n\n"

        if stream_mode:
            response = StreamingHttpResponse(
                generate_streaming_response(), 
                content_type='text/event-stream'
            )
            origin = request.headers.get('Origin')
            if origin:
                response['Access-Control-Allow-Origin'] = origin
            else:
                response['Access-Control-Allow-Origin'] = 'https://www.youtube.com'
            response['Access-Control-Allow-Credentials'] = 'true'
            logger.info(f"Response headers: {response.headers}")
            return response
        else:
            try:
                process_transcription_and_store_embeddings()
                return Response(
                    {"message": "Data processed. Start streaming."},
                    status=status.HTTP_200_OK
                )
            except Exception as e:
                logger.error(f"Failed to process chat: {str(e)}")
                return Response(
                    {"error": f"Something went wrong"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

class VideoSummary(BaseModel):
    summary: str = Field(description="A comprehensive summary of the video content")
    keypoints: List[str] = Field(description="list of 4-5 key points from the video in string format")

class SummaryView(APIView):
    def __init__(self):
        self.parser = PydanticOutputParser(pydantic_object=VideoSummary)
        self.prompt_template = self._create_prompt_template()

    def _create_prompt_template(self) -> PromptTemplate:
        template = """You are an advanced summarization and key points extract assistant specializing in video content analysis.

        Task: You have to provide 2 things, summary and keypoints. Analyze the following video transcript and extract a **concise summary** that captures the **full context** of the video. 
        Also, extract **4 to 5 key points** that highlight the most **important insights or facts** from the transcript. Write answer in **English Language** only even if the transcript is in some other language.

        Requirements:
        1. Summary (500 - 600 words):
        - Capture the main narrative and purpose
        - Include critical context and key discussions

        2. Key Points (4-5):
        - Focus on the most significant insights
        - Be specific and actionable

        Format Instructions:
        {format_instructions}

        Transcript: {transcript}"""

        return PromptTemplate(
            template=template,
            input_variables=["transcript"],
            partial_variables={"format_instructions": self.parser.get_format_instructions()}
        )

    def post(self, request, *args, **kwargs):
        serializer = SummaryInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        validated_data = serializer.validated_data

        youtube_url = validated_data.get('youtube_url')
        transcript = validated_data.get('transcription')
        logger.info(f"Transcript: {transcript}")
        slice_time = validated_data.get('slice_time', -1)
        logger.info(f"Tokens: {len(transcript) // 3.5}")
        if not youtube_url:
            return Response(
                {'youtube_url': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not transcript:
            return Response(
                {'transcription': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST
            )

        response_data = {}
        success = False
        summary = None
        keypoints = None

        try:
            # Check cache first
            if caching:
                video_resource = VideoResource.objects.filter(youtube_url=youtube_url).first()
                if video_resource:
                    video_resource.view_count += 1
                    video_resource.updated = now()
                    video_resource.save()
                    video_resource.slice_time = slice_time

                    response_data = {
                        'success': True,
                        'message': 'YouTube summary retrieved from the database.',
                        'youtube_url': youtube_url,
                        'summary': video_resource.summary,
                        'keypoints': video_resource.keypoints,
                        'slice_time': video_resource.slice_time,
                        'view_count': video_resource.view_count
                    }
                    logger.info("Retrieved from cache")
                    success = True
                    summary = None
                    keypoints = None
                    return JsonResponse(response_data, status=status.HTTP_200_OK)

            response = self._get_summary_keypoints(transcript)
            logger.info(f"Response: {response}")
            success = response["success"]
            if success:
                summary = response["data"]["summary"]
                keypoints = response["data"]["keypoints"]
                response_data = {
                    'success': success,
                    'message': response["display_message"],
                    'youtube_url': youtube_url,
                    'summary': summary,
                    'keypoints': keypoints,
                    'slice_time': slice_time
                }

                return JsonResponse(response_data, status=status.HTTP_200_OK)
            if not success:
                response_data = {
                    'success': success,
                    'error': response["error"],
                    'message': response["display_message"]
                }
                return JsonResponse(response_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except Exception as e:
            response_data = {'error': str(e)}
            return Response(response_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        finally:
            if caching == True and success == True:
                try:
                    if summary and keypoints:
                        logger.info("storing in database")
                        VideoResource.objects.create(
                            youtube_url=youtube_url,
                            summary=summary,
                            keypoints=keypoints,
                            slice_time=slice_time,
                            updated=now()
                        )
                        
                except Exception as db_error:
                    logger.error(f"Database Error: {db_error}")

    def _get_summary_keypoints(self, transcript):
        try:
            formatted_prompt = self.prompt_template.format(transcript=transcript)
            
            # Get LLM with key rotation
            llm = get_llm(streaming=False, temperature=0)
            
            system_message = "You are an advanced summarization and keypoints extract assistant. Your task is to generate a structured summary and key points from a provided video transcript. Focus on capturing the **core message**, important events, and any key takeaways in a **concise, well-structured, and professional** manner. Always respond in **English language** even if the context is in some other language. Ensure the response is strictly in the required JSON format with only 2 fields: 'summary' and 'keypoints'."
            
            full_prompt = f"{system_message}\n\n{formatted_prompt}"
            
            logger.info("Using LLM with key rotation for summary generation")
            
            # Invoke LLM using LangChain interface
            response = llm.invoke(full_prompt)
            
            response_text = response.content
            parsed_response = fix_pydantic_validation(response_text)
            
            if parsed_response is None:
                return {
                    "success": False,
                    "error": "Unable to parse response",
                    "display_message": "Oops! Something went wrong. Please try again."
                }
            
            return {
                "success": True,
                "data": parsed_response,
                "display_message": "Your response has been generated successfully."
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": f"API error: {str(e)}",
                "display_message": "Sorry, there was some error in generating the response. Please try again."
            }

class TokenLimitView(APIView):
    def get(self, request):
        return JsonResponse({"tokens": LLM_MAX_OUTPUT_TOKENS, "charPerToken": 3}, status=status.HTTP_200_OK)

def yt_dlp_download(yt_url: str, output_path: str = None, duration: int = 300) -> str:
    if output_path is None:
        output_path = os.path.join(settings.BASE_DIR, 'media', 'temp')
    os.makedirs(output_path, exist_ok=True)

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': os.path.join(output_path, f'%(title)s_{uuid4().hex}.%(ext)s'),
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'download_ranges': lambda info, *args: [{'start_time': 0, 'end_time': duration}],
        'force_keyframes_at_cuts': True,
    }

    try:
        logger.info(f"Starting download for URL: {yt_url} with duration limit of {duration} seconds")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(yt_url, download=True)
            file_name = ydl.prepare_filename(result)
            mp3_file_path = os.path.splitext(file_name)[0] + '.mp3'

            if not os.path.exists(mp3_file_path):
                if os.path.exists(file_name):
                    logger.warning(f"MP3 conversion might not have happened. Using original file: {file_name}")
                    base, _ = os.path.splitext(file_name)
                    mp3_file_path_temp = base + '.mp3'
                    try:
                        os.rename(file_name, mp3_file_path_temp)
                        mp3_file_path = mp3_file_path_temp
                        logger.info(f"Renamed {file_name} to {mp3_file_path}")
                    except OSError as rename_error:
                        logger.error(f"Could not rename {file_name} to MP3. Error: {rename_error}")
                        raise FileNotFoundError(f"Expected MP3 file not found: {mp3_file_path}")
                else:
                    raise FileNotFoundError(f"Expected MP3 file not found: {mp3_file_path}")

            logger.info(f"Successfully downloaded audio to: {mp3_file_path}")
            return mp3_file_path
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"Failed to download audio from URL {yt_url}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during download: {e}")
        logger.error(traceback.format_exc())
        raise

class TranscribeView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = TranscribeInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        validated_data = serializer.validated_data
        youtube_url = validated_data.get('youtube_url')
        duration = validated_data.get('duration', 300)

        if not youtube_url:
            return Response(
                {'youtube_url': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST
            )

        video_id_match = re.search(r'v=([^&]+)', youtube_url)
        if not video_id_match:
            return Response(
                {'youtube_url': ['Invalid YouTube URL. Must contain a video ID (v=...).']},
                status=status.HTTP_400_BAD_REQUEST
            )
        youtube_video_id = video_id_match.group(1)

        try:
            transcript_entry = VideoTranscripts.objects.filter(youtube_video_id=youtube_video_id).first()
            if transcript_entry and transcript_entry.transcript:
                logger.info(f"Transcript found in database for video ID: {youtube_video_id}")
                result = {'transcription': transcript_entry.transcript}
                return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error checking database for transcript: {e}")
            return Response({'error': 'Database error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        downloaded_file_path = None
        try:
            logger.info(f"Attempting to download audio for: {youtube_url} with duration: {duration} seconds")
            downloaded_file_path = yt_dlp_download(youtube_url, duration=duration)
            logger.info(f"Audio downloaded to: {downloaded_file_path}")

            logger.info(f"Starting transcription for: {downloaded_file_path}")
            
            # Get Groq client with key rotation for transcription
            transcription_client = _get_groq_client()
            
            with open(downloaded_file_path, 'rb') as audio_file:
                transcription = transcription_client.audio.transcriptions.create(
                    file=(os.path.basename(downloaded_file_path), audio_file),
                    model="whisper-large-v3",
                    prompt="Specify context or spelling",
                    temperature=0.0
                )

            if hasattr(transcription, 'text') and isinstance(transcription.text, str):
                transcript_text = transcription.text
            else:
                transcript_text = transcription

            try:
                VideoTranscripts.objects.create(
                    youtube_video_id=youtube_video_id,
                    transcript=transcript_text,
                    updated=now()
                )
                logger.info(f"Transcript cached in database for video ID: {youtube_video_id}")
            except Exception as e:
                logger.error(f"Error caching transcript in database: {e}")

            result = {'transcription': transcript_text}
            logger.info("Transcription successful.")
            return Response(result, status=status.HTTP_200_OK)

        except FileNotFoundError as e:
            logger.error(f"Process failed: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"Download failed: {e}")
            return Response({'error': 'Failed to download audio'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            logger.error(f"Error during transcription: {e}")
            logger.error(traceback.format_exc())
            return Response({'error': 'Transcription failed'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        finally:
            if downloaded_file_path and os.path.exists(downloaded_file_path):
                try:
                    os.remove(downloaded_file_path)
                    logger.info(f"Cleaned up temporary file: {downloaded_file_path}")
                except OSError as e:
                    logger.error(f"Error deleting file {downloaded_file_path}: {e}")
