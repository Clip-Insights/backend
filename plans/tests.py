"""Tests for plan resolution, daily-limit enforcement and the plans API."""
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.timezone import now
from rest_framework import status
from rest_framework.test import APITestCase

from plans.models import Plan, UsageEvent, UserPlan
from plans.services import (
    USAGE_WINDOW,
    LimitExceeded,
    enforce_daily_limit,
    get_plan_for,
    limit_resets_at,
    record_usage,
    remaining,
    usage_summary,
)

User = get_user_model()


def make_user(email="user@test.com"):
    return User.objects.create_user(email=email, name="Test User", password="pass12345")


def reload(user):
    """Fresh instance without cached relations, like a real request's user."""
    return User.objects.get(pk=user.pk)


class PlanResolutionTests(APITestCase):
    def test_anonymous_gets_guest_plan(self):
        self.assertEqual(get_plan_for(None).slug, Plan.GUEST)

    def test_new_user_gets_free_plan_row_on_creation(self):
        # The post_save signal creates the row the moment the account exists.
        user = make_user()
        self.assertEqual(UserPlan.objects.get(user=user).plan.slug, Plan.FREE)
        self.assertEqual(get_plan_for(user).slug, Plan.FREE)

    def test_legacy_user_without_row_selfheals_on_first_request(self):
        # Users created before the plans app have no row; resolving their plan
        # must both answer "free" and create the missing row.
        user = make_user()
        UserPlan.objects.filter(user=user).delete()
        user = reload(user)
        self.assertEqual(get_plan_for(user).slug, Plan.FREE)
        self.assertTrue(UserPlan.objects.filter(user=user, plan__slug=Plan.FREE).exists())

    def test_user_with_active_paid_plan(self):
        user = make_user()
        pro = Plan.objects.get(slug=Plan.PRO)
        # Paddle contract: plan changes are upserts on the existing row.
        UserPlan.objects.update_or_create(
            user=user, defaults={"plan": pro, "expires_at": now() + timedelta(days=30)}
        )
        self.assertEqual(get_plan_for(reload(user)).slug, Plan.PRO)

    def test_expired_paid_plan_falls_back_to_free(self):
        user = make_user()
        pro = Plan.objects.get(slug=Plan.PRO)
        UserPlan.objects.update_or_create(
            user=user, defaults={"plan": pro, "expires_at": now() - timedelta(days=1)}
        )
        self.assertEqual(get_plan_for(user).slug, Plan.FREE)

    def test_inactive_plan_falls_back_to_free(self):
        user = make_user()
        pro = Plan.objects.get(slug=Plan.PRO)
        pro.is_active = False
        pro.save()
        UserPlan.objects.update_or_create(user=user, defaults={"plan": pro})
        self.assertEqual(get_plan_for(user).slug, Plan.FREE)


class DailyLimitTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.free = Plan.objects.get(slug=Plan.FREE)
        self.guest = Plan.objects.get(slug=Plan.GUEST)

    def test_allows_until_limit_then_raises(self):
        for _ in range(self.free.daily_summaries):
            enforce_daily_limit(self.user, self.free, UsageEvent.KIND_SUMMARY)
            record_usage(self.user, UsageEvent.KIND_SUMMARY)

        with self.assertRaises(LimitExceeded) as ctx:
            enforce_daily_limit(self.user, self.free, UsageEvent.KIND_SUMMARY)
        self.assertEqual(ctx.exception.detail["reason"], "daily_summary_limit")
        self.assertEqual(ctx.exception.detail["cta"], "upgrade")
        # All events were just recorded, so the oldest expires ~24h from now.
        resets_at = datetime.fromisoformat(ctx.exception.detail["resets_at"])
        self.assertAlmostEqual(resets_at, now() + USAGE_WINDOW, delta=timedelta(minutes=1))

    def test_zero_limit_means_feature_off(self):
        with self.assertRaises(LimitExceeded) as ctx:
            enforce_daily_limit(self.user, self.guest, UsageEvent.KIND_CHAT)
        self.assertEqual(ctx.exception.detail["reason"], "chat_not_available")
        # Waiting never unlocks a feature the plan doesn't include.
        self.assertNotIn("resets_at", ctx.exception.detail)

    def test_events_outside_window_do_not_count(self):
        record_usage(self.user, UsageEvent.KIND_SUMMARY)
        UsageEvent.objects.update(created_at=now() - timedelta(hours=25))
        self.assertEqual(remaining(self.user, self.free, UsageEvent.KIND_SUMMARY), self.free.daily_summaries)

    def test_resets_at_skips_surplus_events_when_over_limit(self):
        # An admin lowering a plan's limit can leave a user over it; the next
        # allowance then also needs the surplus (oldest) events to expire.
        for _ in range(3):
            record_usage(self.user, UsageEvent.KIND_SUMMARY)
        for event, hours_ago in zip(UsageEvent.objects.order_by("pk"), (3, 2, 1)):
            UsageEvent.objects.filter(pk=event.pk).update(created_at=now() - timedelta(hours=hours_ago))

        # 3 used vs a limit of 2: skip one, so the reset follows the 2h-old event.
        resets_at = limit_resets_at(self.user, UsageEvent.KIND_SUMMARY, skip=1)
        expected = now() - timedelta(hours=2) + USAGE_WINDOW
        self.assertAlmostEqual(resets_at, expected, delta=timedelta(minutes=1))

    def test_usage_summary_shape(self):
        record_usage(self.user, UsageEvent.KIND_CHAT)
        summary = usage_summary(self.user, self.free)
        self.assertEqual(summary["chat"]["used"], 1)
        self.assertEqual(summary["chat"]["limit"], self.free.daily_chat_messages)
        self.assertEqual(summary["chat"]["remaining"], self.free.daily_chat_messages - 1)
        self.assertIn("summary", summary)
        self.assertNotIn("transcription", summary)
        # resets_at tracks when `used` next decreases; null while unused.
        self.assertIsNone(summary["summary"]["resets_at"])
        resets_at = datetime.fromisoformat(summary["chat"]["resets_at"])
        self.assertAlmostEqual(resets_at, now() + USAGE_WINDOW, delta=timedelta(minutes=1))


class PlanEndpointTests(APITestCase):
    def test_plan_list_is_public_and_seeded(self):
        response = self.client.get(reverse("plan-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        slugs = [p["slug"] for p in response.json()["plans"]]
        self.assertEqual(slugs, ["guest", "free", "pro", "premium"])

    def test_plan_list_hides_inactive_plans(self):
        Plan.objects.filter(slug=Plan.PREMIUM).update(is_active=False)
        response = self.client.get(reverse("plan-list"))
        slugs = [p["slug"] for p in response.json()["plans"]]
        self.assertNotIn("premium", slugs)

    def test_my_plan_requires_auth(self):
        response = self.client.get(reverse("my-plan"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_my_plan_selfheals_legacy_user_and_returns_zero_usage(self):
        user = make_user()
        UserPlan.objects.filter(user=user).delete()  # simulate a pre-plans account
        user = reload(user)
        self.client.force_authenticate(user=user)

        response = self.client.get(reverse("my-plan"))
        data = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(data["plan"]["slug"], "free")
        self.assertEqual(data["usage"]["summary"]["used"], 0)
        self.assertTrue(UserPlan.objects.filter(user=user, plan__slug=Plan.FREE).exists())

    def test_my_plan_returns_plan_and_usage(self):
        user = make_user()
        record_usage(user, UsageEvent.KIND_SUMMARY)
        self.client.force_authenticate(user=user)

        response = self.client.get(reverse("my-plan"))
        data = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(data["plan"]["slug"], "free")
        self.assertEqual(data["usage"]["summary"]["used"], 1)
