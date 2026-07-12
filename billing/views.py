import json
import logging

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.models import PaddlePlanMap, Subscription
from billing.serializers import CheckoutInputSerializer
from integrations.registry import get_payment
from plans.models import Plan

logger = logging.getLogger(__name__)


class BillingCatalogView(APIView):
    """Purchase metadata for the pricing page: which plans are buyable, their
    annual price, and the Paddle price ids. Plan limits come from /api/plans/."""

    permission_classes = [AllowAny]

    def get(self, request):
        catalog = [
            {
                "plan_slug": m.plan.slug,
                "monthly_price_usd": float(m.plan.monthly_price_usd),
                "annual_price_usd": float(m.annual_price_usd),
                "paddle_price_id_monthly": m.paddle_price_id_monthly,
                "paddle_price_id_annual": m.paddle_price_id_annual,
            }
            for m in PaddlePlanMap.objects.filter(plan__is_active=True).select_related("plan")
        ]
        return Response({"catalog": catalog})


class SubscriptionView(APIView):
    """The signed-in user's Paddle subscription state (plan/usage: /api/plans/me/)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        subscription = Subscription.objects.filter(user=request.user).select_related("plan").first()
        return Response({
            "subscription": {
                "plan_slug": subscription.plan.slug,
                "status": subscription.status,
                "billing_cycle": subscription.billing_cycle,
                "current_period_end": subscription.current_period_end,
                "cancel_at_period_end": subscription.cancel_at_period_end,
            } if subscription else None,
        })


class CheckoutConfigView(APIView):
    """Everything Paddle.js needs to open the overlay checkout for a plan.

    No server-side transaction is created: the browser opens the checkout with
    a price id, and the webhook brings the resulting subscription back to us
    (with our user id in custom_data).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CheckoutInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        plan_slug = serializer.validated_data["plan_code"]
        cycle = serializer.validated_data["billing_cycle"]

        plan = Plan.objects.filter(slug=plan_slug, is_active=True).first()
        if plan is None or plan.monthly_price_usd <= 0:
            return Response({"plan_code": ["This plan cannot be purchased."]}, status=status.HTTP_400_BAD_REQUEST)

        mapping = PaddlePlanMap.objects.filter(plan=plan).first()
        price_id = mapping and (
            mapping.paddle_price_id_monthly if cycle == "monthly" else mapping.paddle_price_id_annual
        )
        if not price_id:
            return Response(
                {"error": "This plan is not synced with Paddle yet. Run `manage.py setup_billing`."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        payment = get_payment()
        return Response({
            "environment": payment.environment,
            "client_token": payment.client_token,
            "price_id": price_id,
            "email": request.user.email,
            "user_id": str(request.user.id),
        })


class CancelSubscriptionView(APIView):
    """Schedule cancellation at period end (the webhook records the change)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        subscription = Subscription.objects.filter(user=request.user).first()
        if not subscription or not subscription.paddle_subscription_id or not subscription.is_active:
            return Response({"error": "No active subscription to cancel."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            get_payment().cancel_subscription(subscription.paddle_subscription_id)
        except Exception as e:
            logger.error("Paddle cancel failed for %s: %s", subscription.paddle_subscription_id, e)
            return Response({"error": "Cancellation failed. Try again."}, status=status.HTTP_502_BAD_GATEWAY)
        subscription.cancel_at_period_end = True
        subscription.save(update_fields=["cancel_at_period_end", "updated_at"])
        return Response({"msg": "Subscription will cancel at the end of the current period."})


class PaddleWebhookView(APIView):
    """Receives Paddle notifications. Signature-verified, so AllowAny is safe."""

    permission_classes = [AllowAny]
    authentication_classes = []  # Paddle can't send our JWTs

    def post(self, request):
        payment = get_payment()
        signature = request.headers.get("Paddle-Signature", "")
        if not payment.verify_webhook(request.body, signature):
            logger.warning("Rejected Paddle webhook with bad signature")
            return Response({"error": "invalid signature"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            event = json.loads(request.body)
        except json.JSONDecodeError:
            return Response({"error": "invalid payload"}, status=status.HTTP_400_BAD_REQUEST)

        event_type = event.get("event_type", "")
        if event_type.startswith("subscription."):
            from billing.services import apply_subscription_event
            apply_subscription_event(event_type, event.get("data") or {})
        else:
            logger.info("Ignoring Paddle event %s", event_type)
        # Always 200 for processed/ignored events so Paddle doesn't retry forever.
        return Response({"ok": True})
