# Clip Insights

Django REST API for video and PDF insights: transcription, summarization, RAG chat, and file storage.

## Layout

| Path | Purpose |
|------|---------|
| `backend/` | Django 6 app — **git repo lives here** |
| `backend/core/` | Settings, root URLs, health check |
| `backend/account/` | JWT auth, Google OAuth, email |
| `backend/files/` | User file storage (was `userspace`) |
| `backend/videos/` | Transcribe, summarize, chat (was `textutils`) |
| `backend/analytics/` | GA4 ingest via management command |
| `backend/integrations/` | Swappable external services (Protocol + env registry) |
| `backend/utils/` | Shared non-integration utilities (logger) |
| `docs/` | Design specs and implementation plans |

## Run locally

```bash
cd backend
uv run python manage.py runserver
```

Requires `backend/.env` (see `.env` keys in `core/settings.py` and `integrations/keys.py`).

## Architecture rules

- **API contract is fixed** — preserve request/response shapes; old URL paths kept as aliases in `core/urls.py`.
- **Integrations are swappable via env vars** — add a provider file under `integrations/<category>/`, register in `integrations/registry.py`. Do not hardcode vendors in views.
- **Django ORM DB is fixed** (CockroachDB/Postgres). Only the **vector store** layer is swappable.
- **Minimal diff** — no plugin frameworks, no new dependencies unless necessary. Reuse existing patterns.
- **App labels preserved** — `files` uses `label="userspace"`, `videos` uses `label="textutils"` for migration history.

## Key entry points

- URLs: `backend/core/urls.py`
- Integration registry: `backend/integrations/registry.py`
- Env key constants: `backend/integrations/keys.py`
- Video services: `backend/videos/services/`
- Design spec: `docs/superpowers/specs/2026-06-27-backend-modular-apps-design.md`

## Stack

Python 3.13, Django 6, DRF, SimpleJWT, uv, CockroachDB, LangChain, Gemini/Groq/HuggingFace integrations.
