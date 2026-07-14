class NoopPayment:
    """Offline payment provider for tests and smoke runs.

    Returns deterministic fake ids and accepts every webhook signature so the
    billing flow can be exercised without Paddle credentials.
    """

    def __init__(self):
        self.environment = "sandbox"
        self.client_token = "test_noop_client_token"

    def create_product(self, name: str, description: str) -> str:
        return f"pro_noop_{name.lower().replace(' ', '_')}"

    def create_price(self, product_id: str, amount_cents: int, interval: str, name: str) -> str:
        return f"pri_noop_{product_id}_{interval}_{amount_cents}"

    def get_subscription(self, subscription_id: str) -> dict:
        return {"id": subscription_id, "status": "active"}

    def cancel_subscription(self, subscription_id: str) -> dict:
        return {"id": subscription_id, "status": "canceled", "scheduled_change": {"action": "cancel"}}

    def verify_webhook(self, raw_body: bytes, signature_header: str) -> bool:
        return True
