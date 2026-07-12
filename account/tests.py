from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class AccountTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            name="Test User",
            password="testpassword123"
        )
        # create_user makes an inactive, unverified user; activate it so login and
        # JWT-authenticated endpoints work (Django/SimpleJWT reject inactive users).
        self.user.is_active = True
        self.user.is_verified = True
        self.user.save(update_fields=["is_active", "is_verified"])
        self.login_url = "/api/account/login/"
        self.register_url = "/api/account/signup/"
        self.profile_url = "/api/account/profile/"
        self.change_password_url = "/api/account/change-password/"
        self.reset_password_url = "/api/account/reset-password/"
        self.logout_url = "/api/account/logout/"

        self.tokens = RefreshToken.for_user(self.user)
        self.auth_headers = {
            "HTTP_AUTHORIZATION": f"Bearer {self.tokens.access_token}"
        }

    def test_user_registration(self):
        data = {
            "email": "newuser@example.com",
            "name": "New User",
            "password": "newpassword123"
        }
        response = self.client.post(self.register_url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("token", response.data)

    def test_user_login(self):
        data = {"email": "test@example.com", "password": "testpassword123"}
        response = self.client.post(self.login_url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", response.data)

    def test_login_auto_verifies_in_non_production(self):
        unverified = User.objects.create_user(
            email="unverified@example.com",
            name="Unverified",
            password="testpassword123",
        )
        self.assertFalse(unverified.is_active)
        self.assertFalse(unverified.is_verified)

        response = self.client.post(
            self.login_url,
            {"email": "unverified@example.com", "password": "testpassword123"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", response.data)

        unverified.refresh_from_db()
        self.assertTrue(unverified.is_active)
        self.assertTrue(unverified.is_verified)

    def test_login_rejects_bad_password(self):
        response = self.client.post(
            self.login_url,
            {"email": "test@example.com", "password": "wrong"},
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_profile_access(self):
        response = self.client.get(self.profile_url, **self.auth_headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "test@example.com")

    def test_change_password(self):
        data = {"password": "newpassword123"}
        response = self.client.post(
            self.change_password_url, data, **self.auth_headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_password_reset_request(self):
        data = {"email": "test@example.com"}
        response = self.client.post(self.reset_password_url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_logout(self):
        data = {"refresh": str(self.tokens)}
        response = self.client.post(self.logout_url, data, **self.auth_headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
