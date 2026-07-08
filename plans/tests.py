"""Tests for plan resolution, daily-limit enforcement and the plans API."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.timezone import now
from rest_framework import status
from rest_framework.test import APITestCase

from plans.models import Plan, UsageEvent, UserPlan
from plans.services import (
    LimitExceeded,
    enforce_daily_limit,
    get_plan_for,
    record_usage,
    remaining,
    usage_summary,
)

User = get_user_model()


def make_user(email="user@test.com"):
    return User.objects.create_user(email=email, name="Test User", password="pass12345")


class PlanResolutionTests(APITestCase):
    def test_anonymous_gets_guest_plan(self):
        self.assertEqual(get_plan_for(None).slug, Plan.GUEST)

    def test_user_without_user_plan_gets_free(self):
        user = make_user()
        self.assertEqual(get_plan_for(user).slug, Plan.FREE)

    def test_user_with_active_paid_plan(self):
        user = make_user()
        pro = Plan.objects.get(slug=Plan.PRO)
        UserPlan.objects.create(user=user, plan=pro, expires_at=now() + timedelta(days=30))
        self.assertEqual(get_plan_for(user).slug, Plan.PRO)

    def test_expired_paid_plan_falls_back_to_free(self):
        user = make_user()
        pro = Plan.objects.get(slug=Plan.PRO)
        UserPlan.objects.create(user=user, plan=pro, expires_at=now() - timedelta(days=1))
        self.assertEqual(get_plan_for(user).slug, Plan.FREE)

    def test_inactive_plan_falls_back_to_free(self):
        user = make_user()
        pro = Plan.objects.get(slug=Plan.PRO)
        pro.is_active = False
        pro.save()
        UserPlan.objects.create(user=user, plan=pro)
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

    def test_zero_limit_means_feature_off(self):
        with self.assertRaises(LimitExceeded) as ctx:
            enforce_daily_limit(self.user, self.guest, UsageEvent.KIND_CHAT)
        self.assertEqual(ctx.exception.detail["reason"], "chat_not_available")

    def test_events_outside_window_do_not_count(self):
        record_usage(self.user, UsageEvent.KIND_SUMMARY)
        UsageEvent.objects.update(created_at=now() - timedelta(hours=25))
        self.assertEqual(remaining(self.user, self.free, UsageEvent.KIND_SUMMARY), self.free.daily_summaries)

    def test_usage_summary_shape(self):
        record_usage(self.user, UsageEvent.KIND_CHAT)
        summary = usage_summary(self.user, self.free)
        self.assertEqual(summary["chat"]["used"], 1)
        self.assertEqual(summary["chat"]["limit"], self.free.daily_chat_messages)
        self.assertEqual(summary["chat"]["remaining"], self.free.daily_chat_messages - 1)
        self.assertIn("summary", summary)
        self.assertIn("transcription", summary)


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

    def test_my_plan_returns_plan_and_usage(self):
        user = make_user()
        record_usage(user, UsageEvent.KIND_SUMMARY)
        self.client.force_authenticate(user=user)

        response = self.client.get(reverse("my-plan"))
        data = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(data["plan"]["slug"], "free")
        self.assertEqual(data["usage"]["summary"]["used"], 1)
