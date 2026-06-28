"""Smoke test for the health-check endpoint used by Cloud Run."""
from rest_framework.test import APITestCase


class HealthCheckTests(APITestCase):
    def test_health_returns_healthy(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("version", data)
