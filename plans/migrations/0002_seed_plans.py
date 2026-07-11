"""Seed the four launch plans.

Values are the initial self-sustainability estimates (see
docs/PLANS_AND_PRICING.md for the cost math); they are meant to be tuned in
the Django admin without code changes.
"""
from django.db import migrations

SEED_PLANS = [
    {
        "slug": "guest",
        "name": "Guest",
        "description": "Try Clip Insights without an account: notes, screenshots and PDF export.",
        "monthly_price_usd": 0,
        "sort_order": 0,
        "daily_summaries": 0,
        "daily_chat_messages": 0,
        "daily_transcriptions": 0,
        "max_chat_query_chars": 0,
        "transcript_token_budget": 0,
        "max_transcription_seconds": 0,
        "storage_limit_mb": 0,
        "max_file_size_mb": 0,
        "max_note_chars": 500,
        "max_notes_per_video": 10,
        "max_screenshots_per_video": 10,
    },
    {
        "slug": "free",
        "name": "Free",
        "description": "Everything you need to study smarter, free with an account.",
        "monthly_price_usd": 0,
        "sort_order": 1,
        "daily_summaries": 5,
        "daily_chat_messages": 15,
        "daily_transcriptions": 2,
        "max_chat_query_chars": 1000,
        "transcript_token_budget": 8000,
        "max_transcription_seconds": 300,
        "storage_limit_mb": 100,
        "max_file_size_mb": 10,
        "max_note_chars": 1000,
        "max_notes_per_video": 100,
        "max_screenshots_per_video": 40,
    },
    {
        "slug": "pro",
        "name": "Pro",
        "description": "For daily learners: more AI, longer context and 1 GB of storage.",
        "monthly_price_usd": 5,
        "sort_order": 2,
        "daily_summaries": 25,
        "daily_chat_messages": 100,
        "daily_transcriptions": 10,
        "max_chat_query_chars": 2000,
        "transcript_token_budget": 16000,
        "max_transcription_seconds": 600,
        "storage_limit_mb": 1024,
        "max_file_size_mb": 25,
        "max_note_chars": 5000,
        "max_notes_per_video": 300,
        "max_screenshots_per_video": 100,
    },
    {
        "slug": "premium",
        "name": "Premium",
        "description": "Maximum limits for power users, researchers and teams of one.",
        "monthly_price_usd": 12,
        "sort_order": 3,
        "daily_summaries": 50,
        "daily_chat_messages": 200,
        "daily_transcriptions": 20,
        "max_chat_query_chars": 4000,
        "transcript_token_budget": 32000,
        "max_transcription_seconds": 900,
        "storage_limit_mb": 5120,
        "max_file_size_mb": 50,
        "max_note_chars": 10000,
        "max_notes_per_video": 1000,
        "max_screenshots_per_video": 200,
    },
]


def seed_plans(apps, schema_editor):
    Plan = apps.get_model("plans", "Plan")
    for values in SEED_PLANS:
        Plan.objects.update_or_create(slug=values["slug"], defaults=values)


def unseed_plans(apps, schema_editor):
    Plan = apps.get_model("plans", "Plan")
    Plan.objects.filter(slug__in=[p["slug"] for p in SEED_PLANS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("plans", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_plans, unseed_plans),
    ]
