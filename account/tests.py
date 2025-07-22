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
