import json
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils.timezone import now
from rest_framework.test import APIClient

from billing.models import PaddlePlanMap, Subscription
from billing.services import apply_subscription_event, plan_for_price_id
from plans.models import Plan, UserPlan
from plans.services import get_plan_for

User = get_user_model()


def sync_paddle():
    call_command("setup_billing", stdout=StringIO())  # noop provider fills fake ids


def make_user(email="user@test.com"):
    return User.objects.create_user(email=email, name="Test User", password="StrongPass1!")


def effective_plan(user):
    """get_plan_for on a freshly loaded user.

    The signup signal caches the free UserPlan on the in-memory user instance
    (OneToOne reverse cache); webhooks update the row, not that cache. Real
    requests always load a fresh user, so tests must too.
    """
    return get_plan_for(User.objects.get(pk=user.pk))


class SetupBillingCommandTests(TestCase):
    def test_creates_paddle_map_for_paid_plans_only(self):
        sync_paddle()
        slugs = set(PaddlePlanMap.objects.values_list("plan__slug", flat=True))
        self.assertEqual(slugs, {"pro", "premium"})

    def test_idempotent_and_annual_is_ten_months(self):
        sync_paddle()
        first = PaddlePlanMap.objects.get(plan__slug="pro")
        monthly_id, product_id = first.paddle_price_id_monthly, first.paddle_product_id
        sync_paddle()
        again = PaddlePlanMap.objects.get(plan__slug="pro")
        self.assertEqual(again.paddle_price_id_monthly, monthly_id)
        self.assertEqual(again.paddle_product_id, product_id)
        self.assertEqual(float(again.annual_price_usd), float(again.plan.monthly_price_usd) * 10)

    def test_price_id_round_trip(self):
        sync_paddle()
        mapping = PaddlePlanMap.objects.get(plan__slug="premium")
        plan, cycle = plan_for_price_id(mapping.paddle_price_id_annual)
        self.assertEqual((plan.slug, cycle), ("premium", "annual"))
        self.assertEqual(plan_for_price_id("pri_unknown"), (None, None))


class WebhookEventTests(TestCase):
    def setUp(self):
        sync_paddle()
        self.user = make_user()
        self.pro_map = PaddlePlanMap.objects.get(plan__slug="pro")

    def _event_data(self, **overrides):
        data = {
            "id": "sub_123",
            "status": "active",
            "customer_id": "ctm_123",
            "custom_data": {"user_id": str(self.user.id)},
            "items": [{"price": {"id": self.pro_map.paddle_price_id_monthly}}],
            "current_billing_period": {"ends_at": (now() + timedelta(days=30)).isoformat()},
        }
        data.update(overrides)
        return data

    def test_subscription_created_grants_entitlement(self):
        self.assertTrue(apply_subscription_event("subscription.created", self._event_data()))
        self.assertEqual(effective_plan(self.user).slug, "pro")
        sub = Subscription.objects.get(user=self.user)
        self.assertEqual((sub.plan.slug, sub.status, sub.billing_cycle), ("pro", "active", "monthly"))
        user_plan = UserPlan.objects.get(user=self.user)
        self.assertIsNotNone(user_plan.expires_at)  # period end + grace

    def test_annual_price_maps_to_annual_cycle(self):
        data = self._event_data(items=[{"price": {"id": self.pro_map.paddle_price_id_annual}}])
        apply_subscription_event("subscription.created", data)
        self.assertEqual(Subscription.objects.get(user=self.user).billing_cycle, "annual")

    def test_canceled_event_reverts_to_free(self):
        apply_subscription_event("subscription.created", self._event_data())
        apply_subscription_event("subscription.canceled", self._event_data(status="canceled"))
        self.assertEqual(effective_plan(self.user).slug, "free")
        self.assertEqual(Subscription.objects.get(user=self.user).status, "canceled")

    def test_expired_entitlement_falls_back_to_free(self):
        past = (now() - timedelta(days=1)).isoformat()
        apply_subscription_event(
            "subscription.updated", self._event_data(current_billing_period={"ends_at": past}))
        # expires_at = yesterday + 2 days grace = tomorrow -> still pro
        self.assertEqual(effective_plan(self.user).slug, "pro")
        UserPlan.objects.filter(user=self.user).update(expires_at=now() - timedelta(hours=1))
        self.assertEqual(effective_plan(self.user).slug, "free")

    def test_unknown_user_or_price_is_skipped(self):
        self.assertFalse(apply_subscription_event(
            "subscription.created", self._event_data(custom_data={"user_id": None})))
        self.assertFalse(apply_subscription_event(
            "subscription.created", self._event_data(items=[{"price": {"id": "pri_unknown"}}])))
        self.assertFalse(Subscription.objects.exists())


class BillingEndpointTests(TestCase):
    def setUp(self):
        sync_paddle()
        self.user = make_user()
        self.client = APIClient()

    def test_catalog_is_public_and_lists_paid_plans(self):
        response = self.client.get(reverse("billing-catalog"))
        self.assertEqual(response.status_code, 200)
        catalog = {c["plan_slug"]: c for c in response.json()["catalog"]}
        self.assertEqual(set(catalog), {"pro", "premium"})
        self.assertTrue(catalog["pro"]["paddle_price_id_monthly"])
        self.assertEqual(catalog["pro"]["annual_price_usd"], catalog["pro"]["monthly_price_usd"] * 10)

    def test_subscription_endpoint_requires_auth(self):
        self.assertEqual(self.client.get(reverse("billing-subscription")).status_code, 401)

    def test_subscription_endpoint_none_without_subscription(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(reverse("billing-subscription"))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["subscription"])

    def test_checkout_returns_paddle_config(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(reverse("billing-checkout"),
                                    {"plan_code": "pro", "billing_cycle": "annual"}, format="json")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["environment"], "sandbox")
        self.assertEqual(body["user_id"], str(self.user.id))
        self.assertEqual(body["email"], self.user.email)
        self.assertEqual(body["price_id"], PaddlePlanMap.objects.get(plan__slug="pro").paddle_price_id_annual)

    def test_checkout_rejects_free_guest_and_unknown_plans(self):
        self.client.force_authenticate(self.user)
        for slug in ("free", "guest", "nope"):
            response = self.client.post(reverse("billing-checkout"), {"plan_code": slug}, format="json")
            self.assertEqual(response.status_code, 400, slug)

    def test_checkout_unsynced_plan_returns_503(self):
        PaddlePlanMap.objects.all().delete()
        self.client.force_authenticate(self.user)
        response = self.client.post(reverse("billing-checkout"), {"plan_code": "pro"}, format="json")
        self.assertEqual(response.status_code, 503)

    def test_webhook_applies_subscription_event(self):
        mapping = PaddlePlanMap.objects.get(plan__slug="pro")
        payload = {
            "event_type": "subscription.created",
            "data": {
                "id": "sub_wh", "status": "active", "customer_id": "ctm_wh",
                "custom_data": {"user_id": str(self.user.id)},
                "items": [{"price": {"id": mapping.paddle_price_id_monthly}}],
                "current_billing_period": {"ends_at": (now() + timedelta(days=30)).isoformat()},
            },
        }
        response = self.client.post(reverse("billing-webhook"),
                                    json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 200)  # noop provider accepts signature
        self.assertEqual(effective_plan(self.user).slug, "pro")

    def test_webhook_ignores_non_subscription_events(self):
        response = self.client.post(reverse("billing-webhook"),
                                    json.dumps({"event_type": "transaction.completed", "data": {}}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 200)

    def test_cancel_without_subscription_is_400(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post(reverse("billing-cancel")).status_code, 400)

    def test_cancel_active_subscription_schedules_cancellation(self):
        mapping = PaddlePlanMap.objects.get(plan__slug="pro")
        apply_subscription_event("subscription.created", {
            "id": "sub_c", "status": "active", "customer_id": "ctm_c",
            "custom_data": {"user_id": str(self.user.id)},
            "items": [{"price": {"id": mapping.paddle_price_id_monthly}}],
            "current_billing_period": {"ends_at": (now() + timedelta(days=30)).isoformat()},
        })
        self.client.force_authenticate(self.user)
        response = self.client.post(reverse("billing-cancel"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Subscription.objects.get(user=self.user).cancel_at_period_end)


class PaddleSignatureTests(TestCase):
    """Real HMAC verification on the concrete Paddle provider (no API calls)."""

    def test_signature_verification(self):
        import hashlib
        import hmac as hmac_lib
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"PADDLE_WEBHOOK_SECRET": "whsec_test", "PADDLE_ENV": "sandbox"}):
            from integrations.payment.paddle import PaddlePayment
            provider = PaddlePayment()
            body = b'{"event_type":"subscription.created"}'
            good = hmac_lib.new(b"whsec_test", b"123:" + body, hashlib.sha256).hexdigest()
            self.assertTrue(provider.verify_webhook(body, f"ts=123;h1={good}"))
            self.assertFalse(provider.verify_webhook(body, f"ts=124;h1={good}"))
            self.assertFalse(provider.verify_webhook(body, "garbage"))
            self.assertFalse(provider.verify_webhook(body, ""))
