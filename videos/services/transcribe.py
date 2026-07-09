import logging
import os
import re
import traceback
from uuid import uuid4

from django.conf import settings
from django.utils.timezone import now

from integrations.registry import get_transcription
from videos.models import VideoTranscripts

logger = logging.getLogger(__name__)


def yt_dlp_download(yt_url: str, output_path: str = None, duration: int = 300) -> str:
    # Deferred import: yt_dlp is heavy and only needed when a download runs.
    import yt_dlp

    if output_path is None:
        output_path = os.path.join(settings.BASE_DIR, "media", "temp")
    os.makedirs(output_path, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "outtmpl": os.path.join(output_path, f"%(title)s_{uuid4().hex}.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "download_ranges": lambda info, *args: [{"start_time": 0, "end_time": duration}],
        "force_keyframes_at_cuts": True,
    }

    logger.info("Starting download for URL: %s duration=%ss", yt_url, duration)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(yt_url, download=True)
        file_name = ydl.prepare_filename(result)
        mp3_file_path = os.path.splitext(file_name)[0] + ".mp3"

        if not os.path.exists(mp3_file_path):
            if os.path.exists(file_name):
                base, _ = os.path.splitext(file_name)
                mp3_file_path_temp = base + ".mp3"
                os.rename(file_name, mp3_file_path_temp)
                mp3_file_path = mp3_file_path_temp
            else:
                raise FileNotFoundError(f"Expected MP3 file not found: {mp3_file_path}")

    logger.info("Downloaded audio to: %s", mp3_file_path)
    return mp3_file_path


def extract_video_id(youtube_url: str) -> str | None:
    match = re.search(r"v=([^&]+)", youtube_url)
    return match.group(1) if match else None


def transcribe_youtube(youtube_url: str, duration: int = 300) -> dict:
    youtube_video_id = extract_video_id(youtube_url)
    if not youtube_video_id:
        raise ValueError("Invalid YouTube URL. Must contain a video ID (v=...).")

    transcript_entry = VideoTranscripts.objects.filter(youtube_video_id=youtube_video_id).first()
    if transcript_entry and transcript_entry.transcript:
        logger.info("Transcript cache hit for %s", youtube_video_id)
        return {"transcription": transcript_entry.transcript}

    downloaded_file_path = None
    try:
        downloaded_file_path = yt_dlp_download(youtube_url, duration=duration)
        transcript_text = get_transcription().transcribe_file(downloaded_file_path)

        try:
            VideoTranscripts.objects.create(
                youtube_video_id=youtube_video_id,
                transcript=transcript_text,
                updated=now(),
            )
        except Exception as e:
            logger.error("Error caching transcript: %s", e)

        return {"transcription": transcript_text}
    finally:
        if downloaded_file_path and os.path.exists(downloaded_file_path):
            try:
                os.remove(downloaded_file_path)
            except OSError as e:
                logger.error("Error deleting temp file %s: %s", downloaded_file_path, e)
