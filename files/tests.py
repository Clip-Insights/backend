"""Tests for plan-based storage enforcement on file uploads."""
from io import BytesIO
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from files.models import File
from files.utils import storage_info
from plans.models import MB, Plan

User = get_user_model()


def make_user(email="user@test.com"):
    return User.objects.create_user(email=email, name="Test User", password="pass12345")


class FileUploadLimitTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_authenticate(user=self.user)
        self.url = reverse("files")
        self.free = Plan.objects.get(slug=Plan.FREE)

    def _post_pdf(self, size_bytes: int):
        upload = BytesIO(b"x" * size_bytes)
        upload.name = "doc.pdf"
        upload.content_type = "application/pdf"
        return self.client.post(self.url, {"file": upload}, format="multipart")

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self._post_pdf(10)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_file_over_plan_size_limit_returns_429(self):
        response = self._post_pdf(self.free.max_file_size_bytes + 1)
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.json()["reason"], "max_file_size")

    def test_file_exceeding_remaining_storage_returns_429(self):
        used = self.free.storage_limit_bytes - 1 * MB
        File.objects.create(user_id=self.user.id, path="p.com/x", name="big.pdf", size=used)
        response = self._post_pdf(2 * MB)
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.json()["reason"], "storage_limit")

    @patch("files.views.get_storage")
    def test_upload_within_limits_succeeds(self, mock_storage):
        mock_storage.return_value = MagicMock(upload=MagicMock(return_value="https://bucket.com/key.pdf"))
        response = self._post_pdf(1 * MB)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(File.objects.filter(user_id=self.user.id).count(), 1)


class StorageInfoTests(APITestCase):
    def test_allowed_space_comes_from_plan(self):
        user = make_user()
        File.objects.create(user_id=user.id, path="p.com/x", name="a.pdf", size=5 * MB)

        info = storage_info(user)

        free = Plan.objects.get(slug=Plan.FREE)
        self.assertEqual(info["allowed_space"], free.storage_limit_bytes)
        self.assertEqual(info["used_space"], 5 * MB)
        self.assertEqual(info["remaining_space"], free.storage_limit_bytes - 5 * MB)
