import uuid
from django.db import models
from django.utils.timezone import now


class VideoTranscripts(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    youtube_video_id = models.CharField(max_length=30)  # URL for the YouTube video
    transcript = models.TextField(blank=True, null=True)  # Transcript of the video
    updated = models.DateTimeField(default=now)  # Time when the record was last updated

    def __str__(self):
        return f"VideoTranscripts({self.youtube_video_id})"
