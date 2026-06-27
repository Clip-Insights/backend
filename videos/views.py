import logging

import yt_dlp
from django.http import JsonResponse, StreamingHttpResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from integrations.registry import LLM_MAX_OUTPUT_TOKENS
from videos.serializers import ChatInputSerializer, SummaryInputSerializer, TranscribeInputSerializer
from videos.services.chat import build_chat_stream, process_chat_embeddings
from videos.services.summarize import generate_summary
from videos.services.transcribe import transcribe_youtube

logger = logging.getLogger(__name__)


class ChatView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = ChatInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        validated_data = serializer.validated_data

        youtube_url = validated_data.get("youtube_url")
        user_query = validated_data.get("query")
        transcription = validated_data.get("transcription")
        slice_time = validated_data.get("slice_time", -1)
        stream_mode = validated_data.get("stream", False)

        if not youtube_url or not user_query:
            return Response(
                {"youtube_url": ["This field is required."], "query": ["This field is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if stream_mode:
            def generate_streaming_response():
                try:
                    yield from build_chat_stream(youtube_url, user_query, transcription, slice_time)
                except Exception as e:
                    logger.error("Error during chat streaming: %s", e)
                    yield "data: Something went wrong\n\n"

            response = StreamingHttpResponse(
                generate_streaming_response(), content_type="text/event-stream"
            )
            origin = request.headers.get("Origin")
            response["Access-Control-Allow-Origin"] = origin or "https://www.youtube.com"
            response["Access-Control-Allow-Credentials"] = "true"
            return response

        try:
            process_chat_embeddings(youtube_url, transcription, slice_time)
            return Response({"message": "Data processed. Start streaming."}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error("Failed to process chat: %s", e)
            return Response({"error": "Something went wrong"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SummaryView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = SummaryInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        validated_data = serializer.validated_data

        youtube_url = validated_data.get("youtube_url")
        transcript = validated_data.get("transcription")
        slice_time = validated_data.get("slice_time", -1)

        if not youtube_url:
            return Response({"youtube_url": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)
        if not transcript:
            return Response({"transcription": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)

        try:
            data, http_status = generate_summary(youtube_url, transcript, slice_time)
            return JsonResponse(data, status=http_status)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TokenLimitView(APIView):
    def get(self, request):
        return JsonResponse({"tokens": LLM_MAX_OUTPUT_TOKENS, "charPerToken": 3}, status=status.HTTP_200_OK)


class TranscribeView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = TranscribeInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_data = serializer.validated_data
        youtube_url = validated_data.get("youtube_url")
        duration = validated_data.get("duration", 300)

        if not youtube_url:
            return Response({"youtube_url": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = transcribe_youtube(youtube_url, duration=duration)
            return Response(result, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({"youtube_url": [str(e)]}, status=status.HTTP_400_BAD_REQUEST)
        except FileNotFoundError as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except yt_dlp.utils.DownloadError:
            return Response({"error": "Failed to download audio"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            logger.error("Transcription failed: %s", e)
            return Response({"error": "Transcription failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
