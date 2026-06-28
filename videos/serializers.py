from rest_framework import serializers

class ChatInputSerializer(serializers.Serializer):
    youtube_url = serializers.CharField(required=True)
    query = serializers.CharField(required=True)
    transcription = serializers.CharField(required=False, allow_blank=True)
    chat_history = serializers.ListField(child=serializers.DictField(), required=False, default=list)


class SummaryInputSerializer(serializers.Serializer):
    youtube_url = serializers.CharField(required=True)
    transcription = serializers.CharField(required=True)
    slice_time = serializers.IntegerField(required=False, default=-1)

class TranscribeInputSerializer(serializers.Serializer):
    youtube_url = serializers.URLField(required=True)
    duration = serializers.IntegerField(required=False, default=300, min_value=-1)
    