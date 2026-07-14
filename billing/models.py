import uuid

from django.conf import settings
from django.db import models


class PaddlePlanMap(models.Model):
    """Paddle catalog ids for a purchasable plan.

    The plan catalog itself (limits, monthly price) lives in `plans.Plan`;
    this table only maps a plan to the Paddle product/prices the browser
    checkout needs. Populated by `manage.py setup_billing`.
    """

    plan = models.OneToOneField("plans.Plan", on_delete=models.CASCADE, related_name="paddle_map")
    paddle_product_id = models.CharField(max_length=64, blank=True, default="")
    paddle_price_id_monthly = models.CharField(max_length=64, blank=True, default="")
    paddle_price_id_annual = models.CharField(max_length=64, blank=True, default="")
    # Annual is sold at 10x monthly (two months free); stored so the pricing
    # page can display it without recomputing the discount rule.
    annual_price_usd = models.DecimalField(max_digits=7, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.plan.slug} ↔ {self.paddle_product_id or '(unsynced)'}"


class Subscription(models.Model):
    """Mirror of the user's Paddle subscription, maintained by webhooks.

    Plan entitlement itself lives in `plans.UserPlan` (upserted from the same
    webhooks); this row keeps the Paddle-side state we need for cancellation
    and support (ids, status, period end).
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
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="paddle_subscription")
    plan = models.ForeignKey("plans.Plan", on_delete=models.PROTECT, related_name="paddle_subscriptions")
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
        return f"{self.user} -> {self.plan.slug} ({self.status})"
