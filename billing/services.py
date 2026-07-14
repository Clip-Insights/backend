"""Webhook → entitlement synchronisation.

Paddle is the source of truth for payment state. Verified `subscription.*`
events land here and are projected into two rows:

- `plans.UserPlan`   — the entitlement the limit system reads (plan + expiry)
- `billing.Subscription` — the Paddle-side mirror (ids, status, period end)

`UserPlan.expires_at` gets a small grace window past the billing period so a
late renewal webhook doesn't bounce a paying user to the free plan.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils.timezone import now

from billing.models import PaddlePlanMap, Subscription
from plans.models import Plan, UserPlan

logger = logging.getLogger(__name__)

RENEWAL_GRACE = timedelta(days=2)


def plan_for_price_id(price_id: str):
    """Map a Paddle price id back to (plans.Plan, billing_cycle)."""
    mapping = PaddlePlanMap.objects.filter(paddle_price_id_monthly=price_id).select_related("plan").first()
    if mapping:
        return mapping.plan, "monthly"
    mapping = PaddlePlanMap.objects.filter(paddle_price_id_annual=price_id).select_related("plan").first()
    if mapping:
        return mapping.plan, "annual"
    return None, None


@transaction.atomic
def apply_subscription_event(event_type: str, data: dict) -> bool:
    """Apply a verified Paddle `subscription.*` webhook. Returns True if applied."""
    from account.models import User  # local import to avoid app-loading cycles

    custom = data.get("custom_data") or {}
    user_id = custom.get("user_id")
    if not user_id:
        logger.warning("Paddle event %s without custom_data.user_id; skipping", event_type)
        return False
    user = User.objects.filter(pk=user_id).first()
    if not user:
        logger.warning("Paddle event %s for unknown user %s; skipping", event_type, user_id)
        return False

    items = data.get("items") or []
    price_id = (items[0].get("price") or {}).get("id") if items else None
    plan, cycle = plan_for_price_id(price_id or "")
    if plan is None:
        logger.warning("Paddle event %s with unknown price id %r; skipping", event_type, price_id)
        return False

    status = data.get("status", "active")
    period = data.get("current_billing_period") or {}
    ends_at_raw = period.get("ends_at")
    ends_at = parse_datetime(ends_at_raw) if ends_at_raw else None
    scheduled = data.get("scheduled_change") or {}

    Subscription.objects.update_or_create(
        user=user,
        defaults={
            "plan": plan,
            "billing_cycle": cycle,
            "paddle_subscription_id": data.get("id", ""),
            "paddle_customer_id": data.get("customer_id", ""),
            "status": status,
            "current_period_end": ends_at,
            "cancel_at_period_end": scheduled.get("action") == "cancel",
        },
    )

    if status in ("active", "trialing"):
        expires_at = (ends_at + RENEWAL_GRACE) if ends_at else None
        UserPlan.objects.update_or_create(user=user, defaults={"plan": plan, "expires_at": expires_at})
    else:
        # canceled / paused / past_due: entitlement lapses now. (With
        # cancel-at-period-end Paddle keeps status=active until the period is
        # over, so users retain access they have paid for.)
        free = Plan.objects.get(slug=Plan.FREE)
        UserPlan.objects.update_or_create(user=user, defaults={"plan": free, "expires_at": None})

    logger.info("Applied %s for user %s: plan=%s status=%s", event_type, user.pk, plan.slug, status)
    return True
