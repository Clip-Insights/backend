from django.urls import reverse
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from unittest.mock import patch, MagicMock


class DummyLLM:
    def stream(self, prompt, **kwargs):
        yield "Test streaming content"


class ChatViewTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("chat")

    @patch("videos.services.chat.get_vectorstore")
    def test_chat_non_streaming(self, mock_vs):
        mock_vs.return_value.add_texts = MagicMock()
        payload = {
            "youtube_url": "http://youtube.com/dummy",
            "query": "What is this video about?",
            "transcription": "Dummy transcription text.",
            "slice_time": -1,
            "stream": False,
        }
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Data processed. Start streaming.")

    def test_chat_missing_fields(self):
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("videos.services.chat.get_llm", return_value=DummyLLM())
    @patch("videos.services.chat.get_vectorstore")
    def test_chat_streaming(self, mock_vs, mock_llm):
        mock_vs.return_value.add_texts = MagicMock()
        mock_vs.return_value.similarity_search.return_value = []
        payload = {
            "youtube_url": "http://youtube.com/dummy",
            "query": "What is this video about?",
            "transcription": "Dummy transcription text.",
            "slice_time": -1,
            "stream": True,
        }
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        content = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("[DONE]", content)


class SummaryViewTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("summary")

    @patch("videos.services.summarize.generate_summary")
    def test_summary_success(self, mock_generate):
        mock_generate.return_value = ({
            "success": True,
            "summary": "This is a dummy summary.",
            "keypoints": ["Point 1", "Point 2"],
            "message": "Success",
            "youtube_url": "http://youtube.com/dummy",
            "slice_time": -1,
        }, 200)
        payload = {
            "youtube_url": "http://youtube.com/dummy",
            "transcription": "Dummy transcription text.",
            "slice_time": -1,
        }
        response = self.client.post(self.url, payload, format="json")
        data = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(data.get("summary"), "This is a dummy summary.")


class TokenLimitViewTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("tokenlimit")

    def test_tokenlimit(self):
        response = self.client.get(self.url, format="json")
        self.assertIn("tokens", response.json())
