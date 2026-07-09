"""Tests for the videos app: API endpoints + the summarize/chat services.

Runs under both `pytest` and `python manage.py test`. External LLM calls are
patched so the suite is fast, deterministic and offline (FIRST principles).
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from plans.models import Plan, UsageEvent
from plans.services import record_usage
from videos.services.chat import _history_messages, _retrieve_context, build_chat_stream
from videos.services.chunking import chunk_text
from videos.services.summarize import VideoSummary, generate_summary

User = get_user_model()


def make_user(email="user@test.com"):
    return User.objects.create_user(email=email, name="Test User", password="pass12345")


def exhaust(user, kind, limit_field):
    """Record enough usage events to hit the free plan's limit for `kind`."""
    limit = getattr(Plan.objects.get(slug=Plan.FREE), limit_field)
    for _ in range(limit):
        record_usage(user, kind)


class DummyLLM:
    """A stand-in LLM provider used wherever a test patches `get_llm`.

    Records the last chat_stream call so tests can assert on the exact
    system/messages the service builds.
    """

    def __init__(self):
        self.last_system = None
        self.last_messages = None

    def stream(self, prompt, **kwargs):
        yield "Hello "
        yield "world"

    def chat_stream(self, messages, *, system=None, **kwargs):
        self.last_system = system
        self.last_messages = messages
        yield "Hello "
        yield "world"

    def structured(self, prompt, response_model, **kwargs):
        return VideoSummary(summary="A concise summary.", keypoints=["Point 1", "Point 2"])


# --------------------------------------------------------------------------- #
# Chat endpoint
# --------------------------------------------------------------------------- #
class ChatViewTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("chat")
        self.user = make_user()
        self.client.force_authenticate(user=self.user)

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url, {"youtube_url": "http://x", "query": "q"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_daily_limit_returns_structured_429(self):
        exhaust(self.user, UsageEvent.KIND_CHAT, "daily_chat_messages")
        response = self.client.post(
            self.url, {"youtube_url": "http://x", "query": "q", "transcription": "t"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        data = response.json()
        self.assertEqual(data["code"], "limit_exceeded")
        self.assertEqual(data["reason"], "daily_chat_limit")
        self.assertEqual(data["cta"], "upgrade")

    @patch("videos.views.build_chat_stream", return_value=iter(["data: ok\n\n", "data: [DONE]\n\n"]))
    def test_oversized_query_is_truncated_not_rejected(self, mock_stream):
        max_chars = Plan.objects.get(slug=Plan.FREE).max_chat_query_chars
        payload = {
            "youtube_url": "http://x",
            "query": "q" * (max_chars + 500),
            "transcription": "t",
        }
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        b"".join(response.streaming_content)
        sent_query = mock_stream.call_args.args[1]
        self.assertEqual(len(sent_query), max_chars)

    @patch("videos.services.chat.get_llm", return_value=DummyLLM())
    def test_completed_stream_records_one_usage_event(self, _mock_llm):
        payload = {"youtube_url": "http://x", "query": "q", "transcription": "Dummy transcription text."}
        response = self.client.post(self.url, payload, format="json")
        b"".join(response.streaming_content)
        self.assertEqual(UsageEvent.objects.filter(user=self.user, kind=UsageEvent.KIND_CHAT).count(), 1)

    def test_missing_fields_returns_400(self):
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("videos.services.chat.get_llm", return_value=DummyLLM())
    def test_streams_tokens_then_done(self, _mock_llm):
        payload = {
            "youtube_url": "http://youtube.com/dummy",
            "query": "What is this about?",
            "transcription": "Dummy transcription text.",
            "chat_history": [],
        }
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        content = b"".join(response.streaming_content).decode("utf-8")
        # Tokens are JSON-encoded so newlines survive the SSE framing.
        self.assertIn('data: "Hello "', content)
        self.assertIn('data: "world"', content)
        self.assertIn("[DONE]", content)

    @patch("videos.services.chat.get_llm", return_value=DummyLLM())
    def test_history_is_accepted(self, _mock_llm):
        payload = {
            "youtube_url": "http://youtube.com/dummy",
            "query": "And then?",
            "transcription": "Dummy transcription text.",
            "chat_history": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
            ],
        }
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# --------------------------------------------------------------------------- #
# Summary endpoint
# --------------------------------------------------------------------------- #
class SummaryViewTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("summary")
        self.user = make_user()
        self.client.force_authenticate(user=self.user)

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url, {"youtube_url": "http://x", "transcription": "t"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_daily_limit_returns_structured_429(self):
        exhaust(self.user, UsageEvent.KIND_SUMMARY, "daily_summaries")
        response = self.client.post(self.url, {"youtube_url": "http://x", "transcription": "t"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.json()["reason"], "daily_summary_limit")

    @patch("videos.services.summarize.get_llm", return_value=DummyLLM())
    def test_success_records_one_usage_event(self, _mock_llm):
        payload = {"youtube_url": "http://x", "transcription": "t"}
        self.client.post(self.url, payload, format="json")
        self.assertEqual(UsageEvent.objects.filter(user=self.user, kind=UsageEvent.KIND_SUMMARY).count(), 1)

    @patch("videos.views.generate_summary", return_value=({"success": False, "error": "boom"}, 500))
    def test_failure_is_not_charged(self, _mock):
        self.client.post(self.url, {"youtube_url": "http://x", "transcription": "t"}, format="json")
        self.assertEqual(UsageEvent.objects.filter(user=self.user).count(), 0)

    def test_missing_youtube_url_returns_400(self):
        response = self.client.post(self.url, {"transcription": "x"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_transcription_returns_400(self):
        response = self.client.post(self.url, {"youtube_url": "http://x"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("videos.services.summarize.get_llm", return_value=DummyLLM())
    def test_success_returns_summary_and_keypoints(self, _mock_llm):
        payload = {
            "youtube_url": "http://youtube.com/dummy",
            "transcription": "Dummy transcription text.",
            "slice_time": -1,
        }
        response = self.client.post(self.url, payload, format="json")
        data = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(data["success"])
        self.assertEqual(data["summary"], "A concise summary.")
        self.assertEqual(data["keypoints"], ["Point 1", "Point 2"])

    @patch("videos.views.generate_summary", return_value=({"success": False, "error": "boom"}, 500))
    def test_service_error_propagates_status(self, _mock):
        payload = {"youtube_url": "http://x", "transcription": "t"}
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)


# --------------------------------------------------------------------------- #
# Token-limit endpoint
# --------------------------------------------------------------------------- #
class TokenLimitViewTests(APITestCase):
    def test_anonymous_gets_guest_budget(self):
        response = self.client.get(reverse("tokenlimit"), format="json")
        data = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(data["tokens"], Plan.objects.get(slug=Plan.GUEST).transcript_token_budget)
        self.assertEqual(data["charPerToken"], 3)

    def test_authenticated_gets_plan_budget(self):
        self.client.force_authenticate(user=make_user())
        response = self.client.get(reverse("tokenlimit"), format="json")
        self.assertEqual(response.json()["tokens"], Plan.objects.get(slug=Plan.FREE).transcript_token_budget)


# --------------------------------------------------------------------------- #
# Transcribe endpoint (input validation only — no network)
# --------------------------------------------------------------------------- #
class TranscribeViewTests(APITestCase):
    def setUp(self):
        self.url = reverse("transcribe")
        self.user = make_user()
        self.client.force_authenticate(user=self.user)

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url, {"youtube_url": "http://youtube.com/watch?v=x"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_daily_limit_returns_structured_429(self):
        exhaust(self.user, UsageEvent.KIND_TRANSCRIPTION, "daily_transcriptions")
        response = self.client.post(self.url, {"youtube_url": "http://youtube.com/watch?v=x"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.json()["reason"], "daily_transcription_limit")

    @patch("videos.views.transcribe_youtube", return_value={"transcription": "hello"})
    def test_duration_is_clamped_to_plan_and_usage_recorded(self, mock_transcribe):
        max_seconds = Plan.objects.get(slug=Plan.FREE).max_transcription_seconds
        payload = {"youtube_url": "http://youtube.com/watch?v=x", "duration": max_seconds + 999}
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(mock_transcribe.call_args.kwargs["duration"], max_seconds)
        self.assertEqual(
            UsageEvent.objects.filter(user=self.user, kind=UsageEvent.KIND_TRANSCRIPTION).count(), 1
        )

    def test_missing_url_returns_400(self):
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_url_returns_400(self):
        response = self.client.post(self.url, {"youtube_url": "not-a-url"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# --------------------------------------------------------------------------- #
# Service-level unit tests (no HTTP layer)
# --------------------------------------------------------------------------- #
class SummarizeServiceTests(APITestCase):
    @patch("videos.services.summarize.get_llm", return_value=DummyLLM())
    def test_generate_summary_returns_200_payload(self, _mock_llm):
        data, code = generate_summary("http://x", "transcript", -1)
        self.assertEqual(code, 200)
        self.assertTrue(data["success"])
        self.assertEqual(data["summary"], "A concise summary.")
        self.assertEqual(data["slice_time"], -1)

    def test_generate_summary_handles_provider_failure(self):
        class Boom:
            def structured(self, *a, **k):
                raise RuntimeError("provider down")

        with patch("videos.services.summarize.get_llm", return_value=Boom()):
            data, code = generate_summary("http://x", "transcript", -1)
        self.assertEqual(code, 500)
        self.assertFalse(data["success"])
        self.assertIn("error", data)


class ChatServiceTests(APITestCase):
    def test_history_messages_keeps_last_window_and_roles(self):
        history = [{"role": "user", "content": f"m{i}"} for i in range(10)]
        messages = _history_messages(history)
        # Only the last CHAT_MEMORY_WINDOW (3) messages are kept: m7, m8, m9.
        self.assertEqual([m["content"] for m in messages], ["m7", "m8", "m9"])
        self.assertTrue(all(m["role"] == "user" for m in messages))

    def test_history_messages_normalises_roles_and_drops_empty(self):
        history = [
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "   "},
            {"role": "weird", "content": "x"},
        ]
        messages = _history_messages(history)
        self.assertEqual(messages[0], {"role": "assistant", "content": "hi"})
        self.assertEqual(messages[1], {"role": "assistant", "content": "x"})
        self.assertEqual(len(messages), 2)

    def test_history_messages_empty(self):
        self.assertEqual(_history_messages([]), [])

    @patch("videos.services.chat.get_llm", return_value=DummyLLM())
    def test_build_chat_stream_emits_sse_and_done(self, _mock_llm):
        chunks = list(build_chat_stream("http://x", "q", "transcript", []))
        self.assertEqual(chunks[-1], "data: [DONE]\n\n")
        self.assertTrue(any(c.startswith("data: ") for c in chunks[:-1]))

    @patch("videos.services.chat._retrieve_context", return_value="relevant excerpt")
    def test_stream_sends_system_prompt_and_context_in_user_message(self, _ret):
        llm = DummyLLM()
        with patch("videos.services.chat.get_llm", return_value=llm):
            list(build_chat_stream("http://x", "what is this?", "transcript", [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello!"},
            ]))

        self.assertIn("Clip Insights", llm.last_system)
        # History arrives as real chat turns, untouched by the context block.
        self.assertEqual(llm.last_messages[0], {"role": "user", "content": "hi"})
        self.assertEqual(llm.last_messages[1], {"role": "assistant", "content": "hello!"})
        # The final user turn carries the retrieved context + the actual question.
        final = llm.last_messages[-1]
        self.assertEqual(final["role"], "user")
        self.assertIn("relevant excerpt", final["content"])
        self.assertIn("what is this?", final["content"])

    @patch("videos.services.chat._retrieve_context", return_value=None)
    def test_stream_without_transcript_sends_bare_query(self, _ret):
        llm = DummyLLM()
        with patch("videos.services.chat.get_llm", return_value=llm):
            list(build_chat_stream("http://x", "hello!", "", []))
        self.assertEqual(llm.last_messages, [{"role": "user", "content": "hello!"}])

    @patch("videos.services.chat.get_llm")
    def test_stream_json_encodes_tokens_with_newlines(self, mock_llm):
        class NewlineLLM(DummyLLM):
            def chat_stream(self, messages, *, system=None, **kwargs):
                yield "line1\n\nline2"

        mock_llm.return_value = NewlineLLM()
        chunks = list(build_chat_stream("http://x", "q", "", []))
        # The raw newlines must not appear inside the SSE data payload.
        self.assertEqual(chunks[0], 'data: "line1\\n\\nline2"\n\n')


# --------------------------------------------------------------------------- #
# Chat retrieval (RAG) — embeddings + vector store
# --------------------------------------------------------------------------- #
class FakeEmbeddings:
    def embed_documents(self, texts):
        return [[float(len(t)), 0.0] for t in texts]

    def embed_query(self, text):
        return [1.0, 0.0]


class FakeStore:
    def __init__(self):
        self.added = None

    def has_video(self, url):
        return False

    def add_video(self, url, chunks, embeddings):
        self.added = (url, chunks, embeddings)

    def similarity_search(self, url, query_embedding, k):
        return ["chunk-A", "chunk-B", "chunk-C"][:k]


class ChatRetrievalTests(APITestCase):
    TRANSCRIPT = "word " * 400  # long enough to chunk and to clear MIN_TRANSCRIPT_CHARS

    @patch("videos.services.chat.get_vectorstore")
    @patch("videos.services.chat.get_embeddings", return_value=FakeEmbeddings())
    def test_retrieve_embeds_once_and_returns_topk(self, _emb, mock_store):
        store = FakeStore()
        mock_store.return_value = store

        context = _retrieve_context("http://x", self.TRANSCRIPT, "what is this?")

        self.assertEqual(context, "chunk-A\n\nchunk-B\n\nchunk-C")
        self.assertIsNotNone(store.added)  # transcript was embedded + stored

    def test_retrieve_skips_short_transcript(self):
        self.assertIsNone(_retrieve_context("http://x", "too short", "q"))

    @patch("videos.services.chat.get_embeddings", side_effect=RuntimeError("boom"))
    def test_retrieve_returns_none_on_failure(self, _emb):
        self.assertIsNone(_retrieve_context("http://x", self.TRANSCRIPT, "q"))

    @patch("videos.services.chat.get_llm", return_value=DummyLLM())
    @patch("videos.services.chat._retrieve_context", return_value=None)
    def test_stream_falls_back_to_transcript_when_retrieval_unavailable(self, _ret, _llm):
        chunks = list(build_chat_stream("http://x", "q", "some transcript", []))
        self.assertEqual(chunks[-1], "data: [DONE]\n\n")

    def test_chunk_text_overlaps_and_covers(self):
        # size=4, overlap=1 -> step=3, windows start at 0,3,6 and stop once the
        # window reaches the end (no tiny trailing chunk).
        self.assertEqual(chunk_text("abcdefghij", size=4, overlap=1), ["abcd", "defg", "ghij"])

    def test_chunk_text_short_returns_single(self):
        self.assertEqual(chunk_text("short"), ["short"])
        self.assertEqual(chunk_text("   "), [])
