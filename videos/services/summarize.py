import logging
import os
import traceback
from uuid import uuid4

import yt_dlp
from django.conf import settings
from django.utils.timezone import now
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field
from typing import List

from integrations.registry import get_llm
from videos.models import VideoResource
from videos.utils import fix_pydantic_validation

logger = logging.getLogger(__name__)

caching = True


class VideoSummary(BaseModel):
    summary: str = Field(description="A comprehensive summary of the video content")
    keypoints: List[str] = Field(description="list of 4-5 key points from the video in string format")


_parser = PydanticOutputParser(pydantic_object=VideoSummary)
_prompt_template = PromptTemplate(
    template="""You are an advanced summarization and key points extract assistant specializing in video content analysis.

        Task: You have to provide 2 things, summary and keypoints. Analyze the following video transcript and extract a **concise summary** that captures the **full context** of the video. 
        Also, extract **4 to 5 key points** that highlight the most **important insights or facts** from the transcript. Write answer in **English Language** only even if the transcript is in some other language.

        Requirements:
        1. Summary (500 - 600 words):
        - Capture the main narrative and purpose
        - Include critical context and key discussions

        2. Key Points (4-5):
        - Focus on the most significant insights
        - Be specific and actionable

        Format Instructions:
        {format_instructions}

        Transcript: {transcript}""",
    input_variables=["transcript"],
    partial_variables={"format_instructions": _parser.get_format_instructions()},
)


def _get_summary_keypoints(transcript: str) -> dict:
    try:
        formatted_prompt = _prompt_template.format(transcript=transcript)
        system_message = (
            "You are an advanced summarization and keypoints extract assistant. Your task is to generate "
            "a structured summary and key points from a provided video transcript. Focus on capturing the "
            "**core message**, important events, and any key takeaways in a **concise, well-structured, and "
            "professional** manner. Always respond in **English language** even if the context is in some other "
            "language. Ensure the response is strictly in the required JSON format with only 2 fields: "
            "'summary' and 'keypoints'."
        )
        full_prompt = f"{system_message}\n\n{formatted_prompt}"
        response_text = get_llm().complete(full_prompt, temperature=0)
        parsed_response = fix_pydantic_validation(response_text)
        if parsed_response is None:
            return {
                "success": False,
                "error": "Unable to parse response",
                "display_message": "Oops! Something went wrong. Please try again.",
            }
        return {
            "success": True,
            "data": parsed_response,
            "display_message": "Your response has been generated successfully.",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"API error: {str(e)}",
            "display_message": "Sorry, there was some error in generating the response. Please try again.",
        }


def generate_summary(youtube_url: str, transcript: str, slice_time: int) -> tuple[dict, int]:
    """Returns (response_data, http_status)."""
    if caching:
        video_resource = VideoResource.objects.filter(youtube_url=youtube_url).first()
        if video_resource:
            video_resource.view_count += 1
            video_resource.updated = now()
            video_resource.save()
            return {
                "success": True,
                "message": "YouTube summary retrieved from the database.",
                "youtube_url": youtube_url,
                "summary": video_resource.summary,
                "keypoints": video_resource.keypoints,
                "slice_time": slice_time,
                "view_count": video_resource.view_count,
            }, 200

    response = _get_summary_keypoints(transcript)
    if not response["success"]:
        return {
            "success": False,
            "error": response["error"],
            "message": response["display_message"],
        }, 500

    summary = response["data"]["summary"]
    keypoints = response["data"]["keypoints"]

    if caching:
        try:
            VideoResource.objects.create(
                youtube_url=youtube_url,
                summary=summary,
                keypoints=keypoints,
                slice_time=slice_time,
                updated=now(),
            )
        except Exception as db_error:
            logger.error("Database Error: %s", db_error)

    return {
        "success": True,
        "message": response["display_message"],
        "youtube_url": youtube_url,
        "summary": summary,
        "keypoints": keypoints,
        "slice_time": slice_time,
    }, 200
