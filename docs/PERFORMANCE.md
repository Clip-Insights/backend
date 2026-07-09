# Backend performance: cold start & request latency

Measured 2026-07-10 (local, warm disk — Cloud Run cold starts multiply the
import numbers by roughly 3-10x because startup CPU is throttled).

| Cost | Measured | Root cause |
|------|----------|-----------|
| ASGI import + `django.setup()` | 0.56 s | module imports (see below) |
| **First DB query** | **2.29 s** | TLS handshake + session setup to CockroachDB Cloud (eu-central-1) |
| Subsequent query, reused connection | 0.14 s | network RTT only |

## Fixes applied in code

1. **Persistent DB connections** — `CONN_MAX_AGE=600` + `CONN_HEALTH_CHECKS`
   (`core/settings.py`). Django's default closes the connection after every
   request, so *every* API call was paying the ~1-2 s TLS handshake again.
   This is the single biggest win for "summary/chat/everything is slow".
2. **Lazy `yt_dlp` import** (`videos/views.py`, `videos/services/transcribe.py`)
   — ~200 ms of import work removed from every cold start; only the rarely-used
   `/transcribe/` endpoint pays it now.
3. **Bytecode precompiled at build** (`Dockerfile` `compileall`) — with
   `PYTHONDONTWRITEBYTECODE=1` every cold start was re-compiling every module;
   now the image ships `.pyc` files.
4. **Plan lookups cached in-process for 60 s** (`plans/services.py`) — every
   gated endpoint was fetching the Plan row per request.
5. **`--lifespan off`** in `entrypoint.sh` — skips uvicorn's lifespan probe.

## Cloud Run settings (not code — set on the service)

- `--min-instances=1` — the only way to actually eliminate cold starts for the
  first user of the day. Everything else just shrinks them.
- `--cpu-boost` — doubles CPU during startup; directly cuts import time.
- **Deploy in `europe-west3/4`** (or wherever is closest to the CockroachDB
  cluster in AWS eu-central-1). Every ORM query pays the Cloud Run ↔ DB RTT;
  a cross-continent region turns 5 queries into a visible delay.
- Keep `--concurrency` high (80 default is fine) — the app is I/O bound.

## Where the remaining latency lives

Summary/chat time is now dominated by the LLM itself. The switch to
`gemini-3-flash-preview` (2.5-flash retiring) and working embeddings
(`gemini-embedding-001`) means chat streams its first token after
~1 embedding call + model time-to-first-token. If more speed is needed,
`LLM_MODEL=gemini-3.1-flash-lite` is markedly faster for chat-sized replies.
