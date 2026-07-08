from rest_framework import serializers

from .models import Plan

# Every limit clients need; a single list keeps the public and /me payloads identical.
LIMIT_FIELDS = [
    "daily_summaries",
    "daily_chat_messages",
    "daily_transcriptions",
    "max_chat_query_chars",
    "transcript_token_budget",
    "max_transcription_seconds",
    "storage_limit_mb",
    "max_file_size_mb",
    "max_note_chars",
    "max_notes_per_video",
    "max_screenshots_per_video",
]


class PlanSerializer(serializers.ModelSerializer):
    monthly_price_usd = serializers.FloatField()

    class Meta:
        model = Plan
        fields = ["slug", "name", "description", "monthly_price_usd", *LIMIT_FIELDS]
