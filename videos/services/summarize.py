import logging
from typing import List

from pydantic import BaseModel, Field

from integrations.registry import get_llm
from videos.prompts import SUMMARY_PROMPT

logger = logging.getLogger(__name__)


class VideoSummary(BaseModel):
    """Structured output the LLM is constrained to return."""

    summary: str = Field(description="A 500-600 word summary capturing the full context of the video")
    keypoints: List[str] = Field(description="4-5 key points, each a specific, actionable insight from the video")


def generate_summary(youtube_url: str, transcript: str, slice_time: int) -> tuple[dict, int]:
    """Generate a summary and key points for a transcript. Returns (response_data, http_status)."""
    try:
        result = get_llm().structured(SUMMARY_PROMPT.format(transcript=transcript), VideoSummary)
    except Exception as e:
        logger.error("Summary generation failed: %s", e)
        return {
            "success": False,
            "error": f"API error: {str(e)}",
            "message": "Sorry, there was some error in generating the response. Please try again.",
        }, 500

    return {
        "success": True,
        "message": "Your response has been generated successfully.",
        "youtube_url": youtube_url,
        "summary": result.summary,
        "keypoints": result.keypoints,
        "slice_time": slice_time,
    }, 200
