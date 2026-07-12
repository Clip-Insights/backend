import uuid

from django.conf import settings
from django.db import models


class Plan(models.Model):
    """A subscription tier. Paid plans carry the Paddle catalog ids that the
    browser checkout needs; the Free plan has none and simply bounds quotas."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True)  # free | pro | premium
    name = models.CharField(max_length=64)
    price_monthly_usd = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    price_annual_usd = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    monthly_summary_quota = models.IntegerField()
    monthly_chat_quota = models.IntegerField()
    monthly_token_quota = models.BigIntegerField()
    features = models.JSONField(default=list, blank=True)
    paddle_product_id = models.CharField(max_length=64, blank=True, default="")
    paddle_price_id_monthly = models.CharField(max_length=64, blank=True, default="")
    paddle_price_id_annual = models.CharField(max_length=64, blank=True, default="")
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ["sort_order"]

    def __str__(self):
        return self.name


class Subscription(models.Model):
    """One row per user, mirroring the provider's subscription state.

    Webhooks are the source of truth: the row is created/updated only from
    verified Paddle events. A user with no row (or a non-active status) is on
    the Free plan.
    """

    STATUS_CHOICES = [
        ("active", "Active"),
        ("trialing", "Trialing"),
        ("past_due", "Past due"),
        ("paused", "Paused"),
        ("canceled", "Canceled"),
    ]
    CYCLE_CHOICES = [("monthly", "Monthly"), ("annual", "Annual")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscription")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    paddle_subscription_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    paddle_customer_id = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="active")
    billing_cycle = models.CharField(max_length=8, choices=CYCLE_CHOICES, default="monthly")
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_active(self) -> bool:
        return self.status in ("active", "trialing")

    def __str__(self):
        return f"{self.user} -> {self.plan.code} ({self.status})"


class UsagePeriod(models.Model):
    """Per-user usage counters for one calendar month (period = 1st of month)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="usage_periods")
    period = models.DateField()
    summaries_used = models.IntegerField(default=0)
    chats_used = models.IntegerField(default=0)
    tokens_used = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "period"], name="uniq_usage_user_period"),
        ]

    def __str__(self):
        return f"{self.user} {self.period:%Y-%m}"
