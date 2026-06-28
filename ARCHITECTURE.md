# Clip Insights — Backend Architecture

This document is the **single source of truth** for what the Clip Insights backend is and how it works. It describes the system as it is today. For *how to work on it* (standards, workflow, the testing rule), see [AGENTS.md](./AGENTS.md).

---

## 1. Overview

The backend is a **Django + Django REST Framework** API that powers two clients:

- the **browser extension** (`clip-insights-ext`), which augments YouTube watch pages with AI summaries, key points, and a chat-about-the-video feature; and
- the **web app** (`clip-insights-fe`), an account dashboard where users sign in and manage the PDFs they export from the extension (files, folders, storage).

The API is stateless HTTP/JSON. AI generation is delegated to Google Gemini; long-running audio transcription to Groq Whisper; file storage to S3; transactional email to SMTP. Every such third party sits behind a **provider abstraction** so it can be swapped without touching feature code.

> **Chat uses RAG.** The extension sends the (token-budget-sliced) transcript with each chat request. The backend chunks it, embeds the chunks with **Gemini embeddings**, stores them in a **CockroachDB pgvector** vector store keyed by `youtube_url` (embedding once per video), and retrieves only the **top-3 most relevant chunks** to feed the model — never the whole transcript. Embeddings (`EMBEDDING_PROVIDER`) and the vector store (`VECTORSTORE_PROVIDER`) are swappable providers like every other integration; if retrieval fails (e.g. a CockroachDB older than v25.1 without vector support), chat falls back to a bounded slice of the transcript so it degrades gracefully instead of breaking.

---

## 2. Tech stack

| Concern | Choice |
|---|---|
| Language / runtime | Python 3.13 |
| Web framework | Django 6, Django REST Framework |
| Auth | DRF SimpleJWT (access/refresh), custom `account.User`, Google OAuth |
| LLM | Google Gemini via `langchain-google-genai` (stream/complete) + `instructor` (structured output) |
| Transcription | Groq Whisper (`groq`) |
| Object storage | AWS S3 (`boto3`) |
| Database | CockroachDB (`django-cockroachdb` + `psycopg`) |
| Audio download | `yt-dlp` (+ ffmpeg) |
| Server | Uvicorn (ASGI) |
| Packaging | `uv` (`pyproject.toml` + `uv.lock`) |
| Tests | `pytest` + `pytest-django` |
| Deploy | Docker multi-stage → Google Cloud Run |

---

## 3. Repository layout

```
clip-insights-be/
  core/            # project config: settings, urls, asgi/wsgi, health check
  account/         # custom User, registration, login, JWT, Google OAuth, email verify, password reset
  videos/          # the AI features: chat, summary, key points, transcribe, token limit
  files/           # user file/folder CRUD on top of S3 + storage quota
  analytics/       # Google Analytics (GA4) fetch + admin dashboard templates
  integrations/    # provider registry + one subpackage per external capability
  scripts/         # integration_smoke.py and ad-hoc scripts
  utils/           # logger (TracebackFormatter)
  manage.py
  Dockerfile, entrypoint.sh
  pyproject.toml, uv.lock, conftest.py
```

Django app labels: `files`, `account`, `analytics`, and **`textutils`** — the `videos/` directory's app label is `textutils` (set in `videos/apps.py`), so its migrations and DB-level references use `textutils`, not `videos`. The URL prefix `api/textutils/` is a **backward-compat alias** for `api/videos/`, and `api/userspace/` for `api/files/`.

---

## 4. Configuration & environment

Settings live in `core/settings.py` and read from the environment (`.env` via `python-dotenv`). `DEBUG` is on unless `DJANGO_ENV=production`.

Key environment variables:

| Variable | Purpose |
|---|---|
| `DJANGO_ENV` | `production` disables DEBUG |
| `DATABASE_NAME/USER/PASSWORD/HOST/PORT` | CockroachDB connection (sslmode `verify-full`) |
| `LLM_PROVIDER` (default `gemini`) | which LLM provider the registry resolves |
| `LLM_API_KEYS` | comma-separated Gemini keys, rotated round-robin |
| `LLM_MODEL` (default `gemini-2.5-flash`), `LLM_TEMPERATURE`, `LLM_MAX_OUTPUT_TOKENS` | LLM tuning |
| `TRANSCRIPTION_PROVIDER` (default `groq`), `GROQ_API_KEYS` | Whisper transcription |
| `STORAGE_PROVIDER` (default `s3`) + AWS creds/bucket | object storage |
| `EMAIL_PROVIDER` (default `smtp`) + `EMAIL_*` | transactional email |
| `OAUTH_PROVIDER` (default `google`), `GOOGLE_CLIENT_ID` | Google sign-in |
| `ANALYTICS_PROVIDER` (default `ga4`) | analytics fetcher |
| `IMAGE_TAG` | reported by `/health/` |

> **Security debt to be aware of (not yet fixed):** `SECRET_KEY` is hard-coded in `settings.py` and `CORS_ALLOW_ALL_ORIGINS = True`. These are flagged for hardening; do not add new hard-coded secrets, and prefer environment-driven config.

Logging: a rotating file handler writes daily logs under `logs/` (50 MB × 10) plus console, using a custom `TracebackFormatter` (`utils/logger.py`).

---

## 5. The provider registry (the extensibility mechanism)

`integrations/registry.py` is a small dependency-injection container. It maps a *kind* + a *provider name* (from an env var) to a dotted class path, lazily imports and instantiates it once (thread-safe singleton), and hands it back through a `get_<kind>()` accessor.

```python
get_llm()            # LLM_PROVIDER           → gemini | noop
get_transcription()  # TRANSCRIPTION_PROVIDER → groq
get_embeddings()     # EMBEDDING_PROVIDER     → gemini | noop
get_vectorstore()    # VECTORSTORE_PROVIDER   → cockroach | memory
get_storage()        # STORAGE_PROVIDER       → s3
get_email()          # EMAIL_PROVIDER         → smtp | console
get_oauth()          # OAUTH_PROVIDER         → google
get_analytics()      # ANALYTICS_PROVIDER     → ga4 | noop
```

Each kind has a `Protocol` interface in `integrations/<kind>/base.py` that all implementations satisfy (Dependency Inversion). Feature code depends on the accessor + interface, never on a concrete class — so adding/swapping a provider is a new class + one registry entry (Open/Closed).

Provider contracts:

| Kind | Interface (methods) |
|---|---|
| LLM | `complete(prompt) -> str`, `stream(prompt) -> Iterator[str]`, `structured(prompt, response_model) -> BaseModel` |
| Transcription | `transcribe_file(audio_path) -> str` |
| Embeddings | `embed_documents(texts) -> list[list[float]]`, `embed_query(text) -> list[float]` |
| Vector store | `has_video(url) -> bool`, `add_video(url, chunks, embeddings)`, `similarity_search(url, query_embedding, k) -> list[str]` |
| Storage | `upload(key, body, content_type) -> url`, `delete(key)`, `exists(key) -> bool` |
| Email | `send(to, subject, body)` |
| OAuth | `verify(id_token) -> dict` |
| Analytics | `fetch_and_store()` |

The `noop` LLM (`integrations/llm/noop.py`) returns canned responses and is used in tests/smoke runs.

### Gemini provider (`integrations/llm/gemini.py`)

- `complete`/`stream` use LangChain's `ChatGoogleGenerativeAI`.
- `structured` uses **`instructor.from_gemini(... mode=GEMINI_JSON)`** to constrain Gemini to a Pydantic `response_model` and parse the reply into it — no manual JSON/regex.
- API keys are rotated per call via `integrations.keys.APIKeyManager` (a `deque` round-robin), loaded from `LLM_API_KEYS` by `load_api_keys`.

---

## 6. Apps in detail

### 6.1 `videos` — the AI features

URLs (`videos/urls.py`, mounted at `/api/videos/` and `/api/textutils/`):

| Method | Path | View | Purpose |
|---|---|---|---|
| POST | `chat/` | `ChatView` | Streamed (SSE) answer about the video |
| POST | `summary/` | `SummaryView` | Summary + key points from a transcript |
| GET | `tokenlimit/` | `TokenLimitView` | `{tokens, charPerToken}` for client-side transcript slicing |
| POST | `transcribe/` | `TranscribeView` | Whisper transcription of a video's audio |

**Views are thin** (`videos/views.py`): validate via serializers (`videos/serializers.py`), delegate to services, shape responses. Prompts live in `videos/prompts.py`; business logic in `videos/services/`.

- **Summary** (`services/summarize.py`): defines `VideoSummary(summary: str, keypoints: list[str])` and calls `get_llm().structured(SUMMARY_PROMPT.format(transcript=...), VideoSummary)`. Returns `(payload, http_status)`. No caching, no regex. The endpoint returns both summary and key points (the extension renders them in two views).
- **Chat** (`services/chat.py`): RAG over the transcript.
  1. `_retrieve_context` chunks the transcript (`services/chunking.py`, ≈800 chars / 50 overlap), embeds the chunks via `get_embeddings()`, stores them with `get_vectorstore().add_video(url, chunks, vectors)` (only when `has_video(url)` is false, so a video is embedded once), then `similarity_search(url, query_vector, k=3)` returns the **top-3 chunks**.
  2. `build_chat_stream` builds the prompt with `build_chat_prompt(history, context, query)` — the conversational `CHAT_INSTRUCTIONS` (answer from context; if not covered but known, say "not in the video" then answer from general knowledge; if unknown, say the video doesn't discuss it), the **last 3** history messages, and only the retrieved chunks — then yields `data: <token>\n\n` chunks ending with `data: [DONE]\n\n`. `ChatView` wraps it in a `StreamingHttpResponse` with permissive CORS headers for the YouTube origin.
  - **Resilience:** retrieval is wrapped in try/except. A too-short transcript (an error sentinel) or any embedding/store failure returns no context, and chat falls back to a bounded transcript slice — it never crashes the stream.
- **Token limit** (`TokenLimitView`): returns `LLM_MAX_OUTPUT_TOKENS` and a `charPerToken` heuristic (3) the extension uses to slice long transcripts before sending.
- **Transcribe** (`services/transcribe.py`): downloads the first `duration` seconds of audio with `yt-dlp`→mp3, transcribes via `get_transcription()`, and **caches** the result in `VideoTranscripts` keyed by `youtube_video_id` (cache hit short-circuits). Temp files are always cleaned up. (The extension primarily reads transcripts client-side; this endpoint is the audio-based fallback.)

Model (`videos/models.py`): `VideoTranscripts(id: UUID, youtube_video_id, transcript, updated)`.

### 6.2 `account` — identity & auth

Custom user model `account.User` (UUID PK, email login, `name`, `is_active`/`is_verified`/`is_admin`, `allocated_space` default 50 MB). `AUTH_USER_MODEL = "account.User"`.

URLs (`/api/account/`): `signup/`, `login/`, `profile/`, `change-password/`, `reset-password/` (+ `<uid>/<token>/`), `obtain-token/`, `refresh-token/`, `logout/`, `google-login/`, `verify-email/<uid>/<token>/`.

- Registration creates an inactive user and sends an email-verification link; `EmailVerificationView` activates on a valid `uid`/`token`.
- Login issues JWT access/refresh (`get_tokens_for_user`). Access lifetime 600 min, refresh 7 days (`SIMPLE_JWT`). Token blacklist app is enabled for logout.
- `GoogleLoginView` verifies a Google ID token via `get_oauth().verify(...)` and signs the user in.
- Password reset uses signed `uid`/`token` links emailed to the user.

### 6.3 `files` — user file/folder storage

Backs the web app's file manager. All views require `IsAuthenticated`; everything is scoped to `request.user.id`.

URLs (`/api/files/` and `/api/userspace/`): `files/`, `folders/`, `search-files/`, `storage-info/`, `move-file/`, `folder-files/`.

- `FileAPIView` — list / upload (PDF only, deduped names, stored at `userspace/<user>/<uuid>.pdf` via `get_storage().upload`) / rename+move (`PATCH`) / delete (S3 + row).
- `FolderAPIView` — list / create (deduped names) / rename / delete (deletes all contained files from S3 first, with partial-failure reporting via `207`).
- `SearchFilesAPIView`, `MoveFileAPIView`, `FolderFilesAPIView`, `StorageInfoAPIView` (uses `files/utils.storage_info` against the user's `allocated_space`).

Models (`files/models.py`): `File(id, user_id, path, name, created_date, folder_id, size)`, `Folder(id, name, user_id, created_date)`.

### 6.4 `analytics`

Pulls Google Analytics (GA4) data via `get_analytics().fetch_and_store()` (property id / credentials in settings) and renders an admin dashboard from `analytics/templates`. The `noop` provider is available for local/test runs.

### 6.5 `core`

`settings.py`, `urls.py` (admin, health, app includes + compat aliases), `asgi.py`/`wsgi.py`, and `health_check` (`/health/`) which returns `{status: "healthy", version}` — intentionally dependency-light so Cloud Run probes are fast.

---

## 7. AI data flow (end to end)

1. The extension fetches the transcript (client-side) and asks `GET /tokenlimit/` for the budget, then slices the transcript to fit.
2. **Summary/Key Points:** `POST /summary/ {youtube_url, transcription, slice_time}` → `generate_summary` → `get_llm().structured(...)` → `{summary, keypoints}`.
3. **Chat:** `POST /chat/ {youtube_url, query, transcription, chat_history}` → `build_chat_stream` → chunk + embed transcript (once per video) → retrieve top-3 chunks → SSE tokens → `[DONE]`.
4. **Audio fallback:** `POST /transcribe/ {youtube_url, duration}` → yt-dlp → Whisper → cached `VideoTranscripts`.

Chat retrieves the top-3 transcript chunks server-side (Gemini embeddings + CockroachDB pgvector); the model only ever sees those chunks plus the last 3 history messages, not the full transcript.

---

## 8. Testing

- `pytest` + `pytest-django`; config in `pyproject.toml` (`[tool.pytest.ini_options]`, `DJANGO_SETTINGS_MODULE=core.settings`, `python_files` includes `tests.py`). `conftest.py` sets safe provider defaults (`LLM_PROVIDER=noop`, etc.).
- Suites: `videos/tests.py` (endpoints + summarize/chat services + RAG retrieval/chunking, all external calls patched), `integrations/tests.py` (key rotation, registry resolution/singleton, noop LLM, noop embeddings, in-memory vector store), `core/tests.py` (health). Tests run with `EMBEDDING_PROVIDER=noop` + `VECTORSTORE_PROVIDER=memory` so retrieval is exercised fully offline.
- Run with `uv run pytest` or `python manage.py test`. See the **testing rule** in [AGENTS.md](./AGENTS.md): new functionality must keep existing tests green and add its own.

---

## 9. Deployment

`Dockerfile` is multi-stage:

1. **app-deps** — installs dependencies from `pyproject.toml`/`uv.lock` with `uv sync --frozen --no-dev` into `/opt/venv`, and downloads the CockroachDB cert.
2. **production** — copies the venv + cert + app code, runs `collectstatic`, drops to a non-root user, and starts via `entrypoint.sh` (verifies the DB cert, then `uvicorn core.asgi:application`). A `HEALTHCHECK` hits `/health/`.

> The old build had a separate model-downloader stage that baked a ~90 MB sentence-transformers model into the image. RAG now uses **Gemini embeddings** (a hosted API call, no local model), so that stage stays gone and the image carries none of the heavy ML stack (torch/sentence-transformers/transformers/scikit-learn). Embeddings need only `google-generativeai`, already a dependency for the LLM.

---

## 10. Removed / legacy

- **RAG pipeline** is active again, but rebuilt leaner than the original: Gemini embeddings instead of local sentence-transformers (no torch/ML stack), and a CockroachDB vector store that reuses Django's DB connection with raw `VECTOR`/`<=>` SQL (`integrations/vectorstore/cockroach.py`) instead of the old SQLAlchemy/`langchain-postgres` wrapper + separate connection string. The legacy `_LazyProxy`/background warm-up, `videos/ai_config.py`, and `utils/cockroachdb_vectorstore.py` were **not** restored.
- **Summary DB caching**: earlier the summary was cached by URL (which could "poison" a video with a bad early transcript). The current `summarize.py` does **not** cache — every request generates fresh from the supplied transcript.
- `Dockerfile_old` remains as a historical reference and is not used.
