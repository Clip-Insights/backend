from django.contrib import admin
from .models import VideoResource, VideoTranscriptTimeSlice, VideoTranscripts

# Register VideoResource model
@admin.register(VideoResource)
class VideoResourceAdmin(admin.ModelAdmin):
    list_display = ('id', 'youtube_url', 'short_summary', 'short_keypoints', 'updated', 'view_count', 'slice_time')  # Use custom methods for summary and keypoints
    search_fields = ('youtube_url', 'summary', 'keypoints')  # Searchable text fields
    list_filter = ('updated', 'slice_time')  # Filters for date and numeric fields
    readonly_fields = ('id', 'updated', 'view_count')  # Non-editable fields
    fieldsets = (
        (None, {
            'fields': ('id', 'youtube_url', 'summary', 'keypoints', 'slice_time', 'view_count', 'updated')
        }),
    )

    def short_summary(self, obj):
        """Display the first 100 characters of the summary."""
        return obj.summary[:100] + '...' if obj.summary and len(obj.summary) > 100 else obj.summary or ''
    short_summary.short_description = 'Summary'  # Label for admin column

    def short_keypoints(self, obj):
        """Display the first 100 characters of the keypoints."""
        return obj.keypoints[:100] + '...' if obj.keypoints and len(obj.keypoints) > 100 else obj.keypoints or ''
    short_keypoints.short_description = 'Keypoints'  # Label for admin column

    def has_delete_permission(self, request, obj=None):
        # Optional: Restrict deletion if needed
        return True

# Register VideoTranscriptTimeSlice model
@admin.register(VideoTranscriptTimeSlice)
class VideoTranscriptTimeSliceAdmin(admin.ModelAdmin):
    list_display = ('id', 'youtube_url', 'slice_time', 'view_count')  # All fields
    search_fields = ('youtube_url',)  # Searchable text fields
    list_filter = ('slice_time',)  # Filters for numeric fields
    readonly_fields = ('id', 'view_count')  # Non-editable fields
    fieldsets = (
        (None, {
            'fields': ('id', 'youtube_url', 'slice_time', 'view_count')
        }),
    )

# Register VideoTranscripts model
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