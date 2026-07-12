import json
from datetime import date
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from billing.models import Plan, Subscription, UsagePeriod
from billing.services import (
    apply_subscription_event,
    check_quota,
    estimate_tokens,
    get_active_plan,
    record_usage,
)

User = get_user_model()


def seed_plans():
    call_command("setup_billing", "--no-paddle", stdout=StringIO())


def make_user(email="user@test.com"):
    return User.objects.create_user(email=email, name="Test User", password="StrongPass1!")


class PlanSeedingTests(TestCase):
    def test_setup_billing_seeds_three_plans_idempotently(self):
        seed_plans()
        seed_plans()
        self.assertEqual(Plan.objects.count(), 3)
        pro = Plan.objects.get(code="pro")
        self.assertEqual(pro.monthly_summary_quota, 200)
        self.assertEqual(float(pro.price_monthly_usd), 12.0)

    def test_paddle_sync_fills_ids_with_noop_provider(self):
        call_command("setup_billing", stdout=StringIO())
        pro = Plan.objects.get(code="pro")
        self.assertTrue(pro.paddle_product_id.startswith("pro_noop_"))
        self.assertTrue(pro.paddle_price_id_monthly)
        self.assertTrue(pro.paddle_price_id_annual)
        self.assertEqual(Plan.objects.get(code="free").paddle_product_id, "")


class QuotaTests(TestCase):
    def setUp(self):
        seed_plans()
        self.user = make_user()

    def test_defaults_to_free_plan(self):
        self.assertEqual(get_active_plan(self.user).code, "free")

    def test_no_plans_seeded_means_no_enforcement(self):
        Plan.objects.all().delete()
        allowed, info = check_quota(self.user, "summary")
        self.assertTrue(allowed)
        self.assertEqual(info, {})

    def test_summary_quota_blocks_at_limit(self):
        usage = UsagePeriod.objects.create(user=self.user, period=date.today().replace(day=1), summaries_used=15)
        allowed, info = check_quota(self.user, "summary")
        self.assertFalse(allowed)
        self.assertIn("quota", info)
        self.assertEqual(info["used"], 15)

    def test_token_quota_blocks_even_below_action_quota(self):
        UsagePeriod.objects.create(user=self.user, period=date.today().replace(day=1), tokens_used=250_000)
        allowed, info = check_quota(self.user, "chat")
        self.assertFalse(allowed)

    def test_record_usage_increments_counters(self):
        record_usage(self.user, "summary", tokens=9000)
        record_usage(self.user, "chat", tokens=2000)
        usage = UsagePeriod.objects.get(user=self.user)
        self.assertEqual(usage.summaries_used, 1)
        self.assertEqual(usage.chats_used, 1)
        self.assertEqual(usage.tokens_used, 11000)

    def test_active_subscription_upgrades_plan(self):
        pro = Plan.objects.get(code="pro")
        Subscription.objects.create(user=self.user, plan=pro, status="active")
        self.assertEqual(get_active_plan(self.user).code, "pro")

    def test_canceled_subscription_falls_back_to_free(self):
        pro = Plan.objects.get(code="pro")
        Subscription.objects.create(user=self.user, plan=pro, status="canceled")
        self.assertEqual(get_active_plan(self.user).code, "free")

    def test_estimate_tokens_uses_char_heuristic(self):
        self.assertEqual(estimate_tokens("x" * 300), 100)
        self.assertEqual(estimate_tokens(""), 0)


class WebhookEventTests(TestCase):
    def setUp(self):
        call_command("setup_billing", stdout=StringIO())  # noop paddle ids
        self.user = make_user()
        self.pro = Plan.objects.get(code="pro")

    def _event_data(self, **overrides):
        data = {
            "id": "sub_123",
            "status": "active",
            "customer_id": "ctm_123",
            "custom_data": {"user_id": str(self.user.id)},
            "items": [{"price": {"id": self.pro.paddle_price_id_monthly}}],
            "current_billing_period": {"ends_at": "2026-08-01T00:00:00Z"},
        }
        data.update(overrides)
        return data

    def test_subscription_created_activates_plan(self):
        self.assertTrue(apply_subscription_event("subscription.created", self._event_data()))
        sub = Subscription.objects.get(user=self.user)
        self.assertEqual(sub.plan.code, "pro")
        self.assertEqual(sub.status, "active")
        self.assertEqual(sub.billing_cycle, "monthly")
        self.assertEqual(get_active_plan(self.user).code, "pro")

    def test_annual_price_maps_to_annual_cycle(self):
        data = self._event_data(items=[{"price": {"id": self.pro.paddle_price_id_annual}}])
        apply_subscription_event("subscription.created", data)
        self.assertEqual(Subscription.objects.get(user=self.user).billing_cycle, "annual")

    def test_cancellation_event_downgrades(self):
        apply_subscription_event("subscription.created", self._event_data())
        apply_subscription_event("subscription.canceled", self._event_data(status="canceled"))
        self.assertEqual(get_active_plan(self.user).code, "free")

    def test_unknown_user_or_price_is_skipped(self):
        self.assertFalse(apply_subscription_event(
            "subscription.created", self._event_data(custom_data={"user_id": None})))
        self.assertFalse(apply_subscription_event(
            "subscription.created", self._event_data(items=[{"price": {"id": "pri_unknown"}}])))
        self.assertFalse(Subscription.objects.exists())


class BillingEndpointTests(TestCase):
    def setUp(self):
        call_command("setup_billing", stdout=StringIO())
        self.user = make_user()
        self.client = APIClient()

    def test_plans_endpoint_is_public(self):
        response = self.client.get(reverse("billing-plans"))
        self.assertEqual(response.status_code, 200)
        codes = [p["code"] for p in response.json()["plans"]]
        self.assertEqual(codes, ["free", "pro", "premium"])

    def test_subscription_endpoint_requires_auth(self):
        self.assertEqual(self.client.get(reverse("billing-subscription")).status_code, 401)

    def test_subscription_endpoint_returns_plan_and_usage(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(reverse("billing-subscription"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["plan"]["code"], "free")
        self.assertIsNone(body["subscription"])
        self.assertEqual(body["usage"]["summaries_used"], 0)

    def test_checkout_returns_paddle_config(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(reverse("billing-checkout"),
                                    {"plan_code": "pro", "billing_cycle": "annual"}, format="json")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["environment"], "sandbox")
        self.assertEqual(body["user_id"], str(self.user.id))
        self.assertTrue(body["price_id"])

    def test_checkout_rejects_free_and_unknown_plans(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post(reverse("billing-checkout"),
                                          {"plan_code": "free"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(reverse("billing-checkout"),
                                          {"plan_code": "nope"}, format="json").status_code, 400)

    def test_webhook_applies_subscription_event(self):
        pro = Plan.objects.get(code="pro")
        payload = {
            "event_type": "subscription.created",
            "data": {
                "id": "sub_wh", "status": "active", "customer_id": "ctm_wh",
                "custom_data": {"user_id": str(self.user.id)},
                "items": [{"price": {"id": pro.paddle_price_id_monthly}}],
                "current_billing_period": {"ends_at": "2026-08-01T00:00:00Z"},
            },
        }
        response = self.client.post(reverse("billing-webhook"),
                                    json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 200)  # noop provider accepts signature
        self.assertEqual(Subscription.objects.get(user=self.user).plan.code, "pro")


class QuotaEnforcementInVideoViewsTests(TestCase):
    def setUp(self):
        seed_plans()
        self.user = make_user()
        self.client = APIClient()

    def test_anonymous_summary_is_not_metered(self):
        response = self.client.post("/api/videos/summary/",
                                    {"youtube_url": "https://youtube.com/watch?v=x",
                                     "transcription": "words " * 50}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UsagePeriod.objects.exists())

    def test_authenticated_summary_records_usage(self):
        self.client.force_authenticate(self.user)
        response = self.client.post("/api/videos/summary/",
                                    {"youtube_url": "https://youtube.com/watch?v=x",
                                     "transcription": "words " * 50}, format="json")
        self.assertEqual(response.status_code, 200)
        usage = UsagePeriod.objects.get(user=self.user)
        self.assertEqual(usage.summaries_used, 1)
        self.assertGreater(usage.tokens_used, 0)

    def test_over_quota_summary_returns_429(self):
        UsagePeriod.objects.create(user=self.user, period=date.today().replace(day=1), summaries_used=15)
        self.client.force_authenticate(self.user)
        response = self.client.post("/api/videos/summary/",
                                    {"youtube_url": "https://youtube.com/watch?v=x",
                                     "transcription": "words " * 50}, format="json")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"], "quota_exceeded")

    def test_over_quota_chat_returns_429(self):
        UsagePeriod.objects.create(user=self.user, period=date.today().replace(day=1), chats_used=50)
        self.client.force_authenticate(self.user)
        response = self.client.post("/api/videos/chat/",
                                    {"youtube_url": "https://youtube.com/watch?v=x",
                                     "query": "what?", "transcription": "words " * 50}, format="json")
        self.assertEqual(response.status_code, 429)

    def test_authenticated_chat_records_usage_after_stream(self):
        self.client.force_authenticate(self.user)
        response = self.client.post("/api/videos/chat/",
                                    {"youtube_url": "https://youtube.com/watch?v=x",
                                     "query": "what?", "transcription": "words " * 50}, format="json")
        self.assertEqual(response.status_code, 200)
        b"".join(response.streaming_content)  # drain the stream
        usage = UsagePeriod.objects.get(user=self.user)
        self.assertEqual(usage.chats_used, 1)
