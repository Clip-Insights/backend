import uuid

from django.conf import settings
from django.db import models

MB = 1024 * 1024


class Plan(models.Model):
    """A subscription tier and its usage limits.

    Limits are plain typed columns (not a key/value table) so they are
    admin-editable, type-safe, and need no parsing. Daily limits are enforced
    over a rolling 24-hour window. A value of 0 means the feature is off for
    the plan (e.g. all AI limits are 0 for `guest`).
    """

    GUEST = "guest"
    FREE = "free"
    PRO = "pro"
    PREMIUM = "premium"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=30, unique=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    monthly_price_usd = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True, help_text="Inactive plans are hidden from clients")
    sort_order = models.PositiveSmallIntegerField(default=0)

    # AI limits (rolling 24h windows). Summary and key points are one request.
    daily_summaries = models.PositiveIntegerField(default=0)
    daily_chat_messages = models.PositiveIntegerField(default=0)
    daily_transcriptions = models.PositiveIntegerField(default=0)
    max_chat_query_chars = models.PositiveIntegerField(default=0)
    transcript_token_budget = models.PositiveIntegerField(
        default=0, help_text="Max transcript tokens sent per AI request (video token limit)"
    )
    max_transcription_seconds = models.PositiveIntegerField(
        default=0, help_text="Max audio duration transcribed per request"
    )

    # Storage limits
    storage_limit_mb = models.PositiveIntegerField(default=0)
    max_file_size_mb = models.PositiveIntegerField(default=0)

    # Client-enforced limits (notes/screenshots live only in the browser; the
    # backend is still the single source of truth for their values).
    max_note_chars = models.PositiveIntegerField(default=0)
    max_notes_per_video = models.PositiveIntegerField(default=0)
    max_screenshots_per_video = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order"]

    def __str__(self):
        return self.name

    @property
    def storage_limit_bytes(self) -> int:
        return self.storage_limit_mb * MB

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * MB


class UserPlan(models.Model):
    """Which paid plan a user is on. No row (or an inactive plan) means `free`.

    Subscription/payment state is owned by the payments integration (Paddle),
    which only needs to upsert this row on subscribe/renew/cancel.
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_plan")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="user_plans")
    expires_at = models.DateTimeField(
        null=True, blank=True, help_text="After this moment the user falls back to the free plan"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} → {self.plan.slug}"


class UsageEvent(models.Model):
    """Append-only ledger of billable actions, used to count daily usage."""

    KIND_SUMMARY = "summary"
    KIND_CHAT = "chat"
    KIND_TRANSCRIPTION = "transcription"
    KIND_CHOICES = [
        (KIND_SUMMARY, "Summary + key points"),
        (KIND_CHAT, "Chat message"),
        (KIND_TRANSCRIPTION, "Audio transcription"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="usage_events")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "kind", "created_at"])]

    def __str__(self):
        return f"{self.user_id} {self.kind} @ {self.created_at:%Y-%m-%d %H:%M}"
