from unittest import TestCase
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from integrations.email.gmail_api import GmailApiEmailSender
from integrations.oauth.google import GoogleOAuthVerifier

User = get_user_model()


class GoogleOAuthVerifierTests(TestCase):
    @patch("integrations.oauth.google.id_token.verify_oauth2_token")
    @patch("integrations.oauth.google.settings.GOOGLE_CLIENT_ID", "web-client-id")
    @patch("integrations.oauth.google.settings.GOOGLE_EXTENSION_CLIENT_ID", None)
    def test_accepts_web_client_id(self, mock_verify):
        mock_verify.return_value = {"email": "a@b.com", "name": "A"}
        result = GoogleOAuthVerifier().verify("fake-token")
        self.assertEqual(result["email"], "a@b.com")
        mock_verify.assert_called_once()
        self.assertEqual(mock_verify.call_args[0][2], "web-client-id")

    @patch("integrations.oauth.google.id_token.verify_oauth2_token")
    @patch("integrations.oauth.google.settings.GOOGLE_CLIENT_ID", "web-client-id")
    @patch("integrations.oauth.google.settings.GOOGLE_EXTENSION_CLIENT_ID", "ext-client-id")
    def test_falls_back_to_extension_client_id(self, mock_verify):
        mock_verify.side_effect = [ValueError("bad aud"), {"email": "a@b.com", "name": "A"}]
        result = GoogleOAuthVerifier().verify("fake-token")
        self.assertEqual(result["email"], "a@b.com")
        self.assertEqual(mock_verify.call_count, 2)


class GoogleLoginViewTests(APITestCase):
    def setUp(self):
        self.url = "/api/account/google-login/"

    @patch("account.views.get_oauth")
    def test_new_google_user_is_active(self, mock_get_oauth):
        mock_get_oauth.return_value.verify.return_value = {
            "email": "google@example.com",
            "name": "Google User",
        }
        response = self.client.post(self.url, {"token": "valid"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user = User.objects.get(email="google@example.com")
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_verified)
        self.assertIn("token", response.data)

    @patch("account.views.get_oauth")
    def test_existing_inactive_user_is_activated(self, mock_get_oauth):
        user = User.objects.create_user(
            email="inactive@example.com",
            name="Inactive",
            password="unused12345",
        )
        self.assertFalse(user.is_active)

        mock_get_oauth.return_value.verify.return_value = {
            "email": "inactive@example.com",
            "name": "Inactive",
        }
        response = self.client.post(self.url, {"token": "valid"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_verified)


class ResendVerificationViewTests(APITestCase):
    def setUp(self):
        self.url = "/api/account/resend-verification/"

    @patch("account.views.Util.send_verification_email")
    def test_sends_for_unverified_user(self, mock_send):
        User.objects.create_user(
            email="pending@example.com",
            name="Pending",
            password="testpassword123",
        )
        response = self.client.post(
            self.url, {"email": "pending@example.com"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_send.assert_called_once()

    @patch("account.views.Util.send_verification_email")
    def test_unknown_email_returns_generic_success(self, mock_send):
        response = self.client.post(
            self.url, {"email": "missing@example.com"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_send.assert_not_called()


class GmailApiEmailSenderTests(TestCase):
    @patch("integrations.email.gmail_api.build")
    def test_send_calls_gmail_api(self, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        with patch.dict(
            "os.environ",
            {
                "GMAIL_REFRESH_TOKEN": "refresh",
                "GMAIL_CLIENT_ID": "cid",
                "GMAIL_CLIENT_SECRET": "secret",
            },
        ):
            GmailApiEmailSender().send(
                to="user@example.com",
                subject="Hello",
                body="Body",
            )

        mock_service.users().messages().send.assert_called_once()
