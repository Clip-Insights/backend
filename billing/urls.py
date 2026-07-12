from django.urls import path

from billing.views import (
    CancelSubscriptionView,
    CheckoutConfigView,
    PaddleWebhookView,
    PlanListView,
    SubscriptionView,
)

urlpatterns = [
    path("plans/", PlanListView.as_view(), name="billing-plans"),
    path("subscription/", SubscriptionView.as_view(), name="billing-subscription"),
    path("checkout/", CheckoutConfigView.as_view(), name="billing-checkout"),
    path("cancel/", CancelSubscriptionView.as_view(), name="billing-cancel"),
    path("webhook/", PaddleWebhookView.as_view(), name="billing-webhook"),
]
