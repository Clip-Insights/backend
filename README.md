# Clip Insights — Backend

Django + Django REST Framework API that powers the [Clip Insights](https://github.com/Clip-Insights) browser extension and web app. It handles authentication, plans and usage limits, file storage, and the AI features: transcription, summaries, key points, and RAG-based chat about a video.

The API is stateless HTTP/JSON. Every external service (LLM, embeddings, transcription, storage, email, OAuth, analytics) sits behind a provider abstraction and is selected by an environment variable, so vendors can be swapped without touching feature code.

> For the full design — the provider registry, per-app internals, the RAG data flow, and deployment details — see **[ARCHITECTURE.md](./ARCHITECTURE.md)**. For contributor standards and the testing rule, see **[AGENTS.md](./AGENTS.md)**.

## What it does

- **Auth & accounts** (`account/`) — email/password signup with email verification, JWT access/refresh tokens, Google OAuth sign-in, password reset.
- **Plans & limits** (`plans/`) — guest / free / pro / premium tiers with per-user usage limits enforced on the AI endpoints; Paddle billing integration.
- **AI features** (`videos/`):
  - `POST /api/videos/summary/` — summary + key points from a transcript.
  - `POST /api/videos/chat/` — streamed (SSE) answer about the video, using RAG over the transcript.
  - `POST /api/videos/transcribe/` — Whisper transcription of a video's audio (fallback when a transcript can't be read client-side).
  - `GET /api/videos/tokenlimit/` — token budget the client uses to slice long transcripts.
- **File storage** (`files/`) — per-user PDF files and folders backed by S3, with a storage quota. Powers the web app's file manager.
- **Analytics** (`analytics/`) — GA4 ingest and an admin dashboard.

### How chat works (RAG)

The client sends the transcript with each chat request. The backend chunks it, embeds the chunks once per video, stores the vectors in a **CockroachDB pgvector** store keyed by the video URL, and retrieves only the **top-3 most relevant chunks** to feed the model — never the whole transcript. If retrieval fails, chat degrades gracefully to a bounded slice of the transcript instead of breaking. See [ARCHITECTURE.md](./ARCHITECTURE.md) for the details.

## Tech stack

| Concern | Choice |
|---|---|
| Language / runtime | Python 3.13 |
| Framework | Django 6, Django REST Framework |
| Auth | DRF SimpleJWT, custom `account.User`, Google OAuth |
| LLM / embeddings | Pluggable (Google Gemini, Fireworks AI via the OpenAI SDK) + `instructor` for structured output |
| Transcription | Groq Whisper |
| Vector store | CockroachDB pgvector (swappable; in-memory for tests) |
| Object storage | AWS S3 (`boto3`) |
| Database | CockroachDB (`django-cockroachdb` + `psycopg`) |
| Audio download | `yt-dlp` (+ ffmpeg) |
| Server | Uvicorn (ASGI) |
| Packaging | `uv` (`pyproject.toml` + `uv.lock`) |
| Tests | `pytest` + `pytest-django` |
| Deploy | Docker (multi-stage) → Google Cloud Run |

## Prerequisites

- **Python 3.13** (see `.python-version`)
- **[uv](https://docs.astral.sh/uv/)** for dependency management
- **ffmpeg** on `PATH` (used by `yt-dlp` for the transcription fallback)
- A **CockroachDB** (or Postgres) database. CockroachDB **v25.1+** is required for the pgvector-backed chat retrieval; older versions still work but chat falls back to a transcript slice.

## Setup

```bash
# 1. Install dependencies into a local virtualenv
uv sync

# 2. Create your environment file (see the table below)
#    Set the keys in .env — there is no committed example file.

# 3. Apply migrations
uv run python manage.py migrate

# 4. Run the dev server
uv run python manage.py runserver
```

The API is served at `http://127.0.0.1:8000/`. Health check: `GET /health/`.

### Environment variables

Settings live in `core/settings.py` and are read from `.env` (via `python-dotenv`). `DEBUG` is on unless `DJANGO_ENV=production`. The most important keys:

| Variable | Purpose |
|---|---|
| `DJANGO_ENV` | Set to `production` to disable `DEBUG` |
| `SECRET_KEY` | Django secret key |
| `DATABASE_NAME` / `USER` / `PASSWORD` / `HOST` / `PORT` | CockroachDB connection |
| `DATABASE_CERT_PATH` | Path to the CockroachDB CA certificate (`sslmode=verify-full`) |
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_TEMPERATURE`, `LLM_MAX_OUTPUT_TOKENS` | LLM selection and tuning |
| `LLM_API_KEYS` | Comma-separated LLM keys (rotated round-robin) |
| `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` | Embeddings for RAG |
| `VECTORSTORE_PROVIDER` | `cockroach` (prod) or `memory` (tests) |
| `TRANSCRIPTION_PROVIDER`, `GROQ_API_KEYS` | Whisper transcription |
| `STORAGE_PROVIDER`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_STORAGE_BUCKET_NAME`, `AWS_REGION` | S3 file storage |
| `EMAIL_PROVIDER`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`, `EMAIL_URL_DOMAIN`, `RESEND_API_KEY` | Transactional email (`smtp` / `console` / `resend`) |
| `OAUTH_PROVIDER`, `GOOGLE_CLIENT_ID`, `GOOGLE_EXTENSION_CLIENT_ID` | Google sign-in (web app + extension client IDs) |
| `ANALYTICS_PROVIDER` | `ga4` or `noop` |

Provider names map to concrete classes in `integrations/registry.py`; env key constants live in `integrations/keys.py`. See [ARCHITECTURE.md](./ARCHITECTURE.md) for the complete matrix.

## Testing

```bash
uv run pytest                 # or: uv run python manage.py test
```

`conftest.py` sets safe provider defaults (`LLM_PROVIDER=noop`, `EMBEDDING_PROVIDER=noop`, `VECTORSTORE_PROVIDER=memory`) so the suite — including the full RAG retrieval path — runs offline with no external calls. Per the testing rule in [AGENTS.md](./AGENTS.md), new functionality must keep existing tests green and add its own.

## Deployment

The `Dockerfile` is a multi-stage build (dependency install → slim production image) that runs `collectstatic`, drops to a non-root user, and starts via `entrypoint.sh` (verifies the DB certificate, then launches `uvicorn core.asgi:application`). A `HEALTHCHECK` hits `/health/`. The target platform is **Google Cloud Run**, which injects `$PORT`.

```bash
docker build -t clip-insights-be .
docker run -p 8080:8080 --env-file .env clip-insights-be
```

## Project layout

```
clip-insights-be/
  core/           # settings, root URLs, ASGI/WSGI, health check
  account/        # custom User, auth, JWT, Google OAuth, email
  videos/         # AI features: chat (RAG), summary, key points, transcribe
  files/          # user file/folder storage on S3 + quota
  plans/          # plans, per-user usage limits & enforcement
  analytics/      # GA4 ingest + admin dashboard
  integrations/   # provider registry + one subpackage per external service
  utils/          # shared utilities (logger)
  scripts/        # smoke tests and ad-hoc scripts
  docs/           # design specs and implementation plans
  manage.py, Dockerfile, entrypoint.sh, pyproject.toml, uv.lock
```

> Two Django app labels differ from their directory names for migration continuity: `videos/` has the label `textutils` and `files/` has `userspace`. The URL prefixes `/api/textutils/` and `/api/userspace/` are backward-compatible aliases for `/api/videos/` and `/api/files/`.

## Related repositories

- **[chrome-extension](https://github.com/Clip-Insights/chrome-extension)** — the browser extension client
- **[clip-insights-fe](https://github.com/zubayr-ahmad/clip-insights-fe)** — the web app / account dashboard
