import logging

from django.http import JsonResponse, StreamingHttpResponse
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from plans.models import UsageEvent
from plans.services import enforce_daily_limit, get_plan_for, record_usage
from videos.serializers import ChatInputSerializer, SummaryInputSerializer
from videos.services.chat import build_chat_stream
from videos.services.summarize import generate_summary

logger = logging.getLogger(__name__)

# Estimated characters per LLM token, shared with clients via TokenLimitView.
CHARS_PER_TOKEN = 3


class ChatView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = ChatInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        validated_data = serializer.validated_data

        youtube_url = validated_data.get("youtube_url")
        user_query = validated_data.get("query")
        transcription = validated_data.get("transcription")
        chat_history = validated_data.get("chat_history", [])

        if not youtube_url or not user_query:
            return Response(
                {"youtube_url": ["This field is required."], "query": ["This field is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        plan = get_plan_for(request.user)
        enforce_daily_limit(request.user, plan, UsageEvent.KIND_CHAT)

        # Oversized input is truncated, not rejected: the user still gets an
        # answer and the client warns about the cut (see product requirement).
        user_query = user_query[: plan.max_chat_query_chars]
        transcript_budget_chars = plan.transcript_token_budget * CHARS_PER_TOKEN
        if transcription:
            transcription = transcription[:transcript_budget_chars]

        user = request.user

        def generate_streaming_response():
            try:
                yield from build_chat_stream(youtube_url, user_query, transcription, chat_history)
                # Charge only after a completed stream so provider failures are free.
                record_usage(user, UsageEvent.KIND_CHAT)
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


class SummaryView(APIView):
    permission_classes = [IsAuthenticated]

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

        plan = get_plan_for(request.user)
        enforce_daily_limit(request.user, plan, UsageEvent.KIND_SUMMARY)
        transcript = transcript[: plan.transcript_token_budget * CHARS_PER_TOKEN]

        try:
            data, http_status = generate_summary(youtube_url, transcript, slice_time)
            if http_status == 200:
                record_usage(request.user, UsageEvent.KIND_SUMMARY)
            return JsonResponse(data, status=http_status)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TokenLimitView(APIView):
    """Transcript token budget for the caller's plan (guest plan when anonymous).

    Clients use this to slice transcripts before sending them to AI endpoints.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        plan = get_plan_for(request.user)
        return JsonResponse(
            {"tokens": plan.transcript_token_budget, "charPerToken": CHARS_PER_TOKEN},
            status=status.HTTP_200_OK,
        )
