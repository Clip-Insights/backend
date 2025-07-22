from django.urls import reverse
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from unittest.mock import patch


class DummyChunk:
    def __init__(self, content):
        self.content = content


class DummyLLM:
    def stream(self, prompt):
        yield DummyChunk("Test streaming content")
        yield DummyChunk("[DONE]")


class DummyChromaCollection:
    def query(self, **kwargs):
        return {"documents": [["dummy context"]]}

    def add(self, **kwargs):
        pass


class ChatViewTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('chat')
        patcher = patch(
            'textutils.views.CHROMA_COLLECTION',
            DummyChromaCollection()
        )
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_chat_missing_fields(self):
        response = self.client.post(self.url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('youtube_url', response.data)
        self.assertIn('query', response.data)

    def test_chat_non_streaming(self):
        payload = {
            "youtube_url": "http://youtube.com/dummy",
            "query": "What is this video about?",
            "transcription": "Dummy transcription text.",
            "slice_time": -1,
            "stream": False
        }
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("message", response.data)
        self.assertEqual(
            response.data["message"],
            "Data processed. Start streaming."
        )

    @patch('textutils.views.get_llm', return_value=DummyLLM())
    def test_chat_streaming(self, mock_get_llm):
        payload = {
            "youtube_url": "http://youtube.com/dummy",
            "query": "What is this video about?",
            "transcription": "Dummy transcription text.",
            "slice_time": -1,
            "stream": True
        }
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.get('Content-Type'), 'text/event-stream')
        content = b"".join(response.streaming_content).decode('utf-8')
        self.assertIn("[DONE]", content)


class SummaryViewTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('summary')

    def test_summary_missing_youtube_url(self):
        payload = {
            "transcription": "Dummy transcription text.",
            "slice_time": -1
        }
        response = self.client.post(self.url, payload, format='json')
        data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("youtube_url", data)

    def test_summary_missing_transcription(self):
        payload = {
            "youtube_url": "http://youtube.com/dummy",
            "slice_time": -1
        }
        response = self.client.post(self.url, payload, format='json')
        data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("transcription", data)

    @patch('textutils.views.SummaryView._get_summary_keypoints')
    def test_summary_success(self, mock_get_summary_keypoints):
        dummy_response = {
            "success": True,
            "data": {
                "summary": "This is a dummy summary.",
                "keypoints": ["Point 1", "Point 2", "Point 3", "Point 4"]
            },
            "display_message": "Success"
        }
        mock_get_summary_keypoints.return_value = dummy_response
        payload = {
            "youtube_url": "http://youtube.com/dummy",
            "transcription": "Dummy transcription text.",
            "slice_time": -1
        }
        response = self.client.post(self.url, payload, format='json')
        data = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            data.get("summary"),
            dummy_response["data"]["summary"]
        )
        self.assertEqual(
            data.get("keypoints"),
            dummy_response["data"]["keypoints"]
        )


class TokenLimitViewTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('tokenlimit')

    def test_tokenlimit(self):
        response = self.client.get(self.url, format='json')
        self.assertEqual(
            response.json(), {
                "tokens": 50000, "charPerToken": 2.5}
        )
