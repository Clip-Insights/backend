import uuid
from django.db import models
from django.utils.timezone import now

class VideoResource(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # Unique string ID
    youtube_url = models.URLField(unique=True)  # URL for the YouTube video
    summary = models.TextField(blank=True, null=True)  # Optional summary of the video
    keypoints = models.TextField(blank=True, null=True)  # Optional key points of the video
    updated = models.DateTimeField(default=now)  # Time when the record was last updated
    view_count = models.PositiveIntegerField(default=0)  # Number of times accessed
    slice_time = models.FloatField(default=0)  # Time slice for the video in seconds. -1 means complete video
    def __str__(self):
        return f"VideoResource({self.youtube_url})"

    def increment_access_count(self):
        """Increments the view count by 1."""
        self.view_count += 1
        self.save()


# Model is for storing timeslice for the videos. This timeslice will be used for transcript and chatting.
class VideoTranscriptTimeSlice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    youtube_url = models.URLField()  # URL for the YouTube video
    slice_time = models.FloatField(default=0)  # Time slice for the video in seconds. -1 means complete video
    view_count = models.PositiveIntegerField(default=0)  # Number of times accessed, every query in the chat will increase this.

    def __str__(self):
        return f"{self.youtube_url} - {self.slice_time} seconds"
    
    def increment_access_count(self):
        """Increments the view count by 1."""
        self.view_count += 1
        self.save()

class VideoTranscripts(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    youtube_video_id = models.CharField(max_length=30)  # URL for the YouTube video
    transcript = models.TextField(blank=True, null=True)  # Transcript of the video
    updated = models.DateTimeField(default=now)  # Time when the record was last updated

    def __str__(self):
        return f"VideoTranscripts({self.youtube_video_id})"