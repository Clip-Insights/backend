"""Plan resolution and usage-limit enforcement.

The flow every gated endpoint follows:

    plan = get_plan_for(request.user)
    enforce_daily_limit(request.user, plan, UsageEvent.KIND_X)   # raises LimitExceeded (429)
    ... do the work ...
    record_usage(request.user, UsageEvent.KIND_X)                # only charge successes

Guests (unauthenticated requests) never reach the enforcement step: gated views
use IsAuthenticated, so they receive 401 and the clients show a sign-up prompt.
"""
import logging
import time
from datetime import datetime, timedelta

from django.utils.timezone import now
from rest_framework.exceptions import APIException

from .models import Plan, UsageEvent, UserPlan

logger = logging.getLogger(__name__)

USAGE_WINDOW = timedelta(hours=24)

# Plans change rarely (admin edits only), so a short in-process cache saves a
# DB round-trip on every gated request. Kept small on purpose: worst case an
# admin edit takes up to PLAN_CACHE_TTL seconds to reach a running instance.
PLAN_CACHE_TTL = 60.0
_plan_cache: dict[str, tuple[Plan, float]] = {}


def _get_plan(slug: str) -> Plan:
    cached = _plan_cache.get(slug)
    if cached and cached[1] > time.monotonic():
        return cached[0]
    plan = Plan.objects.get(slug=slug)
    _plan_cache[slug] = (plan, time.monotonic() + PLAN_CACHE_TTL)
    return plan

# Maps a usage kind to its limit column on Plan and a human message.
DAILY_LIMIT_FIELDS = {
    UsageEvent.KIND_SUMMARY: ("daily_summaries", "summaries"),
    UsageEvent.KIND_CHAT: ("daily_chat_messages", "chat messages"),
}


class LimitExceeded(APIException):
    """Structured 429 so clients can render the right CTA without guessing.

    `resets_at` is the UTC ISO-8601 moment the rolling window returns an
    allowance; clients render it in the viewer's local timezone. It is omitted
    (not null — DRF coerces None in detail dicts to the string 'None') when
    waiting doesn't help (feature not in the plan, storage full).
    """

    status_code = 429
    default_code = "limit_exceeded"

    def __init__(self, reason: str, message: str, cta: str = "upgrade", resets_at: datetime | None = None):
        detail = {"code": "limit_exceeded", "reason": reason, "message": message, "cta": cta}
        if resets_at:
            detail["resets_at"] = resets_at.isoformat()
        super().__init__(detail=detail)


def ensure_user_plan(user) -> UserPlan:
    """The user's UserPlan row, creating a free one if it doesn't exist yet.

    New users get their row from the post_save signal; this covers accounts
    created before the plans app existed, so their first authenticated request
    self-heals the missing row (and /plans/me/ shows real zeroed usage).
    """
    user_plan = getattr(user, "user_plan", None)
    if user_plan is None:
        user_plan, _ = UserPlan.objects.get_or_create(
            user=user, defaults={"plan": _get_plan(Plan.FREE)}
        )
    return user_plan


def get_plan_for(user) -> Plan:
    """Effective plan: guest for anonymous, the user's active unexpired plan, else free."""
    if user is None or not getattr(user, "is_authenticated", False):
        return _get_plan(Plan.GUEST)

    user_plan = ensure_user_plan(user)
    if user_plan.plan.is_active:
        if user_plan.expires_at is None or user_plan.expires_at > now():
            return user_plan.plan
    return _get_plan(Plan.FREE)


def usage_in_window(user, kind: str) -> int:
    return UsageEvent.objects.filter(user=user, kind=kind, created_at__gte=now() - USAGE_WINDOW).count()


def limit_resets_at(user, kind: str, skip: int = 0) -> datetime | None:
    """UTC moment the rolling window next returns an allowance for `kind`.

    Allowances come back one at a time, exactly USAGE_WINDOW after each event,
    so the next one frees up when the oldest counted event leaves the window.
    `skip` ignores that many oldest events — used when consumption exceeds the
    current limit (an admin lowered it), because the surplus events must
    expire before the first free slot appears. None when nothing is counted.
    """
    oldest = list(
        UsageEvent.objects.filter(user=user, kind=kind, created_at__gte=now() - USAGE_WINDOW)
        .order_by("created_at")
        .values_list("created_at", flat=True)[skip : skip + 1]
    )
    return oldest[0] + USAGE_WINDOW if oldest else None


def enforce_daily_limit(user, plan: Plan, kind: str) -> None:
    """Raise LimitExceeded when the user has no allowance left for `kind`."""
    field, label = DAILY_LIMIT_FIELDS[kind]
    limit = getattr(plan, field)
    if limit == 0:
        raise LimitExceeded(
            reason=f"{kind}_not_available",
            message=f"Your {plan.name} plan does not include {label}. Upgrade to unlock this feature.",
        )
    used = usage_in_window(user, kind)
    if used >= limit:
        cta = "upgrade" if plan.slug != Plan.PREMIUM else "wait"
        raise LimitExceeded(
            reason=f"daily_{kind}_limit",
            message=f"You have used all {limit} {label} available in a 24-hour period."
            + (" Upgrade your plan for more." if cta == "upgrade" else ""),
            cta=cta,
            resets_at=limit_resets_at(user, kind, skip=used - limit),
        )


def record_usage(user, kind: str) -> None:
    UsageEvent.objects.create(user=user, kind=kind)


def remaining(user, plan: Plan, kind: str) -> int:
    field, _ = DAILY_LIMIT_FIELDS[kind]
    return max(0, getattr(plan, field) - usage_in_window(user, kind))


def usage_summary(user, plan: Plan) -> dict:
    """Per-kind {used, limit, remaining, resets_at} map for /plans/me/.

    `resets_at` (UTC ISO-8601, null when nothing is counted) is when `used`
    next decreases, so clients can show when a depleted limit unblocks.
    """
    summary = {}
    for kind, (field, _) in DAILY_LIMIT_FIELDS.items():
        limit = getattr(plan, field)
        used = usage_in_window(user, kind)
        resets_at = limit_resets_at(user, kind)
        summary[kind] = {
            "used": used,
            "limit": limit,
            "remaining": max(0, limit - used),
            "resets_at": resets_at.isoformat() if resets_at else None,
        }
    return summary
