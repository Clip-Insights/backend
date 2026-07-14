from django.urls import path

from billing.views import (
    BillingCatalogView,
    CancelSubscriptionView,
    CheckoutConfigView,
    PaddleWebhookView,
    SubscriptionView,
)

urlpatterns = [
    path("catalog/", BillingCatalogView.as_view(), name="billing-catalog"),
    path("subscription/", SubscriptionView.as_view(), name="billing-subscription"),
    path("checkout/", CheckoutConfigView.as_view(), name="billing-checkout"),
    path("cancel/", CancelSubscriptionView.as_view(), name="billing-cancel"),
    path("webhook/", PaddleWebhookView.as_view(), name="billing-webhook"),
]
