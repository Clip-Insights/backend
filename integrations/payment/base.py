from typing import Protocol


class PaymentProvider(Protocol):
    """Contract every payment provider must satisfy.

    The provider owns all vendor-specific API calls and webhook verification;
    feature code (the `billing` app) only ever talks to this interface.
    """

    environment: str  # "sandbox" | "live"
    client_token: str  # public token the browser checkout uses

    def create_product(self, name: str, description: str) -> str:
        """Create a catalog product; returns the provider's product id."""
        ...

    def create_price(self, product_id: str, amount_cents: int, interval: str, name: str) -> str:
        """Create a recurring price (interval: 'month'|'year'); returns the price id."""
        ...

    def get_subscription(self, subscription_id: str) -> dict:
        """Fetch a subscription's current state from the provider."""
        ...

    def cancel_subscription(self, subscription_id: str) -> dict:
        """Schedule cancellation at the end of the current billing period."""
        ...

    def verify_webhook(self, raw_body: bytes, signature_header: str) -> bool:
        """Return True iff the webhook payload signature is valid."""
        ...
