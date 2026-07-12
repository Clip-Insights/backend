"""Plan resolution, usage metering, and quota enforcement.

Metering counts **estimated tokens** using the same chars-per-token heuristic
the clients already use for transcript slicing (see `TokenLimitView`), so the
numbers are consistent end to end and provider-agnostic.
"""
import logging
from datetime import date

from django.db import transaction
from django.db.models import F

from billing.models import Plan, Subscription, UsagePeriod

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN = 3  # keep in sync with TokenLimitView's charPerToken
FREE_PLAN_CODE = "free"

# Canonical tier catalog (seeded by `manage.py setup_billing`). Quotas follow
# the pricing plan: actions are what users understand; tokens bound abuse.
PLAN_CATALOG = [
    {
        "code": "free",
        "name": "Free",
        "price_monthly_usd": "0",
        "price_annual_usd": "0",
        "monthly_summary_quota": 15,
        "monthly_chat_quota": 50,
        "monthly_token_quota": 250_000,
        "sort_order": 0,
        "features": [
            "All core capture features",
            "Screenshots & notes (unlimited)",
            "PDF export & upload",
            "15 AI summaries / month",
            "50 AI chat messages / month",
        ],
    },
    {
        "code": "pro",
        "name": "Pro",
        "price_monthly_usd": "12",
        "price_annual_usd": "108",
        "monthly_summary_quota": 200,
        "monthly_chat_quota": 800,
        "monthly_token_quota": 3_500_000,
        "sort_order": 1,
        "features": [
            "Everything in Free",
            "200 AI summaries / month",
            "800 AI chat messages / month",
            "Priority AI responses",
            "Full chat history & memory",
        ],
    },
    {
        "code": "premium",
        "name": "Premium",
        "price_monthly_usd": "29",
        "price_annual_usd": "278",
        "monthly_summary_quota": 800,
        "monthly_chat_quota": 3000,
        "monthly_token_quota": 13_800_000,
        "sort_order": 2,
        "features": [
            "Everything in Pro",
            "800 AI summaries / month",
            "3,000 AI chat messages / month",
            "Audio transcription fallback",
            "Early access to new platforms",
        ],
    },
]

_ACTION_FIELDS = {"summary": "summaries_used", "chat": "chats_used"}
_ACTION_QUOTAS = {"summary": "monthly_summary_quota", "chat": "monthly_chat_quota"}


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def get_active_plan(user) -> Plan | None:
    """The user's effective plan: their active subscription's plan, else Free.

    Returns None when no plans are seeded yet — callers treat that as
    'billing not configured' and skip enforcement rather than break the API.
    """
    subscription = Subscription.objects.filter(user=user).select_related("plan").first()
    if subscription and subscription.is_active:
        return subscription.plan
    return Plan.objects.filter(code=FREE_PLAN_CODE, is_active=True).first()


def get_usage(user) -> UsagePeriod:
    period = date.today().replace(day=1)
    usage, _ = UsagePeriod.objects.get_or_create(user=user, period=period)
    return usage


def check_quota(user, action: str) -> tuple[bool, dict]:
    """Return (allowed, info). `info` always carries plan/usage for the client."""
    plan = get_active_plan(user)
    if plan is None:  # billing not seeded — never block existing behaviour
        return True, {}

    usage = get_usage(user)
    used = getattr(usage, _ACTION_FIELDS[action])
    quota = getattr(plan, _ACTION_QUOTAS[action])
    info = {
        "plan": plan.code,
        "action": action,
        "used": used,
        "quota": quota,
        "tokens_used": usage.tokens_used,
        "token_quota": plan.monthly_token_quota,
    }
    if used >= quota:
        info["reason"] = f"Monthly {action} quota reached ({quota}). Upgrade your plan to continue."
        return False, info
    if usage.tokens_used >= plan.monthly_token_quota:
        info["reason"] = "Monthly token quota reached. Upgrade your plan to continue."
        return False, info
    return True, info


def record_usage(user, action: str, tokens: int) -> None:
    """Atomically bump the user's counters for the current period."""
    try:
        usage = get_usage(user)
        UsagePeriod.objects.filter(pk=usage.pk).update(
            tokens_used=F("tokens_used") + max(0, tokens),
            **{_ACTION_FIELDS[action]: F(_ACTION_FIELDS[action]) + 1},
        )
    except Exception:  # metering must never take down the AI features
        logger.exception("Failed to record %s usage for user %s", action, user.pk)


def plan_for_price_id(price_id: str) -> tuple[Plan, str] | tuple[None, None]:
    """Map a Paddle price id back to (plan, billing_cycle)."""
    plan = Plan.objects.filter(paddle_price_id_monthly=price_id).first()
    if plan:
        return plan, "monthly"
    plan = Plan.objects.filter(paddle_price_id_annual=price_id).first()
    if plan:
        return plan, "annual"
    return None, None


@transaction.atomic
def apply_subscription_event(event_type: str, data: dict) -> bool:
    """Apply a verified Paddle `subscription.*` webhook to our state.

    Identity comes from `custom_data.user_id` (set at checkout); the plan from
    the subscription item's price id. Returns True when state was updated.
    """
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

    period = data.get("current_billing_period") or {}
    scheduled = data.get("scheduled_change") or {}
    Subscription.objects.update_or_create(
        user=user,
        defaults={
            "plan": plan,
            "billing_cycle": cycle,
            "paddle_subscription_id": data.get("id", ""),
            "paddle_customer_id": data.get("customer_id", ""),
            "status": data.get("status", "active"),
            "current_period_end": period.get("ends_at"),
            "cancel_at_period_end": scheduled.get("action") == "cancel",
        },
    )
    logger.info("Subscription %s for user %s -> plan=%s status=%s", event_type, user.pk, plan.code, data.get("status"))
    return True
