import hashlib
import hmac
import logging
import os

import requests

logger = logging.getLogger(__name__)

_BASE_URLS = {
    "sandbox": "https://sandbox-api.paddle.com",
    "live": "https://api.paddle.com",
}


class PaddlePayment:
    """Paddle Billing API client (products, prices, subscriptions, webhooks).

    Paddle is a Merchant of Record: the checkout itself runs in the browser via
    Paddle.js, so this class only covers the server side — catalog setup,
    subscription management, and webhook signature verification.
    """

    def __init__(self):
        self.environment = os.getenv("PADDLE_ENV", "sandbox").lower()
        if self.environment not in _BASE_URLS:
            raise ValueError(f"PADDLE_ENV must be 'sandbox' or 'live', got {self.environment!r}")
        self._base_url = _BASE_URLS[self.environment]
        self._api_key = os.getenv("PADDLE_API_KEY", "")
        self.client_token = os.getenv("PADDLE_CLIENT_TOKEN", "")
        self._webhook_secret = os.getenv("PADDLE_WEBHOOK_SECRET", "")

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        if not self._api_key:
            raise RuntimeError("PADDLE_API_KEY is not configured")
        response = requests.request(
            method,
            f"{self._base_url}{path}",
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            timeout=30,
        )
        body = response.json() if response.content else {}
        if not response.ok:
            logger.error("Paddle API %s %s failed (%s): %s", method, path, response.status_code, body)
            raise RuntimeError(f"Paddle API error {response.status_code}: {body.get('error', body)}")
        return body.get("data", body)

    def create_product(self, name: str, description: str) -> str:
        data = self._request(
            "POST",
            "/products",
            {"name": name, "description": description, "tax_category": "saas"},
        )
        return data["id"]

    def create_price(self, product_id: str, amount_cents: int, interval: str, name: str) -> str:
        data = self._request(
            "POST",
            "/prices",
            {
                "product_id": product_id,
                "description": name,
                "unit_price": {"amount": str(amount_cents), "currency_code": "USD"},
                "billing_cycle": {"interval": interval, "frequency": 1},
                "quantity": {"minimum": 1, "maximum": 1},
            },
        )
        return data["id"]

    def get_subscription(self, subscription_id: str) -> dict:
        return self._request("GET", f"/subscriptions/{subscription_id}")

    def cancel_subscription(self, subscription_id: str) -> dict:
        return self._request(
            "POST",
            f"/subscriptions/{subscription_id}/cancel",
            {"effective_from": "next_billing_period"},
        )

    def verify_webhook(self, raw_body: bytes, signature_header: str) -> bool:
        """Validate Paddle's `Paddle-Signature: ts=...;h1=...` header (HMAC-SHA256)."""
        if not self._webhook_secret:
            logger.error("PADDLE_WEBHOOK_SECRET is not configured; rejecting webhook")
            return False
        try:
            parts = dict(item.split("=", 1) for item in signature_header.split(";"))
            timestamp, received = parts["ts"], parts["h1"]
        except (ValueError, KeyError, AttributeError):
            return False
        signed_payload = f"{timestamp}:".encode() + raw_body
        expected = hmac.new(self._webhook_secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, received)
