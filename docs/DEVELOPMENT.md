# Local development

Setup, configuration, build, and verification instructions for the backend.

## Prerequisites

- **Python 3.13** (see `.python-version`)
- **[uv](https://docs.astral.sh/uv/)** for dependency management
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

Retired transcription integrations are outside the public API; the extension reads video captions directly.

### Environment variables

Settings live in `core/settings.py` and are read from `.env` (via `python-dotenv`). `DEBUG` is on unless `DJANGO_ENV=production`. The most important keys:

| Variable | Purpose |
|---|---|
| `DJANGO_ENV` | Set to `production` to disable `DEBUG` |
| `DATABASE_NAME` / `USER` / `PASSWORD` / `HOST` / `PORT` | CockroachDB connection |
| `DATABASE_CERT_PATH` | Path to the CockroachDB CA certificate (`sslmode=verify-full`) |
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_TEMPERATURE`, `LLM_MAX_OUTPUT_TOKENS` | LLM selection and tuning |
| `FIREWORKS_API_KEYS` / `LLM_API_KEYS` | Fireworks / Gemini keys for the selected provider (comma-separated, rotated round-robin) |
| `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` | Embeddings for RAG |
| `VECTORSTORE_PROVIDER` | `cockroach` (prod) or `memory` (tests) |
| `STORAGE_PROVIDER`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_STORAGE_BUCKET_NAME`, `AWS_REGION` | S3 file storage |
| `EMAIL_PROVIDER`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`, `EMAIL_URL_DOMAIN`, `RESEND_API_KEY` | Transactional email (`smtp` / `console` / `resend`) |
| `OAUTH_PROVIDER`, `GOOGLE_CLIENT_ID`, `GOOGLE_EXTENSION_CLIENT_ID` | Google sign-in (web app + extension client IDs) |
| `ANALYTICS_PROVIDER` | `ga4` or `noop` |

Provider names map to concrete classes in `integrations/registry.py`; env key constants live in `integrations/keys.py`. See [ARCHITECTURE.md](../ARCHITECTURE.md) for the complete matrix.

## Testing

```bash
uv run pytest                 # or: uv run python manage.py test
```

`conftest.py` sets safe provider defaults (`LLM_PROVIDER=noop`, `EMBEDDING_PROVIDER=noop`, `VECTORSTORE_PROVIDER=memory`) so the suite — including the full RAG retrieval path — runs offline with no external calls. Per the testing rule in [AGENTS.md](../AGENTS.md), new functionality must keep existing tests green and add its own.

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
  billing/        # checkout configuration, subscriptions, and webhooks
  analytics/      # GA4 ingest + admin dashboard
  integrations/   # provider registry + one subpackage per external service
  utils/          # shared utilities (logger)
  scripts/        # smoke tests and ad-hoc scripts
  docs/           # design specs and implementation plans
  manage.py, Dockerfile, entrypoint.sh, pyproject.toml, uv.lock
```

> Two Django app labels differ from their directory names for migration continuity: `videos/` has the label `textutils` and `files/` has `userspace`. The URL prefixes `/api/textutils/` and `/api/userspace/` are backward-compatible aliases for `/api/videos/` and `/api/files/`.

