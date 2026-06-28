from django.contrib import admin
from .models import VideoTranscripts


@admin.register(VideoTranscripts)
class VideoTranscriptsAdmin(admin.ModelAdmin):
    list_display = ('id', 'youtube_video_id', 'short_transcript', 'updated')  # Use custom method for transcript
    search_fields = ('youtube_video_id', 'transcript')  # Searchable text fields
    list_filter = ('updated',)  # Filters for date fields
    readonly_fields = ('id', 'updated')  # Non-editable fields
    fieldsets = (
        (None, {
            'fields': ('id', 'youtube_video_id', 'transcript', 'updated')
        }),
    )

    def short_transcript(self, obj):
        """Display the first 100 characters of the transcript."""
        return obj.transcript[:100] + '...' if obj.transcript and len(obj.transcript) > 100 else obj.transcript or ''
    short_transcript.short_description = 'Transcript'  # Label for admin column
