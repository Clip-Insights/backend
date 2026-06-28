# AGENTS.md — Clip Insights Backend

**Role:** You are a senior Django/DRF backend engineer working on the Clip Insights API. You own a task end to end: understand it, plan it, implement it to the standards below, test it, and self-review before finishing.

This file is **standards and guidelines only**. For *what the system is and how it works* (apps, endpoints, data flow, providers, deployment), read [ARCHITECTURE.md](./ARCHITECTURE.md) — it is the single source of truth for project detail.

---

## Tech stack (at a glance)

- **Python 3.13**, **Django 6 + Django REST Framework**.
- **Package manager: `uv`** (`pyproject.toml` + `uv.lock`). The `.venv` has no `pip` — never invoke pip.
- **LLM:** Google Gemini via `langchain-google-genai` (streaming/complete) and **`instructor`** for structured output.
- **RAG (chat):** Gemini embeddings + a CockroachDB pgvector vector store; chat retrieves the top-3 transcript chunks (see ARCHITECTURE.md §6.1, "Chat"). Keep it lean — use the existing provider Protocols and Django's DB connection; do **not** pull in `langchain`/`langchain-postgres`/SQLAlchemy/local sentence-transformers.
- **DB:** CockroachDB (`django-cockroachdb` + `psycopg`).
- **Tests:** `pytest` + `pytest-django` (also runnable via `manage.py test`).

## Commands

```bash
uv sync                       # install/refresh deps from the lockfile
uv run pytest                 # run the whole test suite
uv run pytest videos          # run one app's tests
uv run python manage.py test  # same suite via Django's runner
uv add <pkg>                  # add a runtime dependency (updates pyproject + uv.lock)
uv add --dev <pkg>            # add a dev/test dependency
```

After changing `pyproject.toml` dependencies, run `uv lock` so `uv sync --frozen` (used in the Docker build) stays valid.

---

## Workflow for every change

1. **Discover** — read the relevant code and [ARCHITECTURE.md](./ARCHITECTURE.md) before editing. Match existing patterns.
2. **Plan** — keep the change minimal and within the existing architecture (see principles below).
3. **Implement** — follow the coding standards.
4. **Test** — see the testing rule. This is non-negotiable.
5. **Self-review** — re-read the diff; check the anti-patterns list; confirm tests and `manage.py check` pass.

---

## Design principles (apply with judgement, not dogma)

- **SRP / DIP** — keep concerns separate and depend on abstractions. New third-party capabilities (LLM, storage, email, OAuth, analytics, transcription) go behind a provider **Protocol** in `integrations/<kind>/base.py`, with a concrete implementation registered in `integrations/registry.py`. Feature/service code calls `get_<kind>()`, never a concrete class.
- **Open/Closed** — add a new provider by adding a class + a registry entry; don't edit call sites.
- **DRY** — one authoritative representation of each piece of knowledge; extract only after the rule of three.
- **KISS / YAGNI** — solve today's problem simply. Don't add configuration, abstraction layers, or "future-proofing" that nothing uses. (RAG is back, but deliberately lean — Gemini embeddings + raw `VECTOR` SQL over Django's connection, no heavy ML/`langchain` stack.)

## Coding standards

- **Thin views, logic in services.** DRF views validate input (via serializers) and shape responses; business logic lives in `videos/services/*`. Keep views free of LLM/provider details.
- **Prompts live in `videos/prompts.py`** as named templates with `{placeholders}`. Don't inline prompt strings in services.
- **Structured LLM output uses Pydantic + `instructor`** (`get_llm().structured(prompt, Model)`). Do not hand-roll JSON/regex parsing of model output.
- **Validate at the boundary** with DRF serializers; never trust request data directly.
- **Secrets come from the environment** (`os.getenv`), never hard-coded. API keys are comma-separated and rotated via `integrations.keys.APIKeyManager`.
- **Logging, not prints.** Use module `logging`; log errors with context. User-facing error responses must be generic (no stack traces / provider internals).
- **Comments explain *why*, not *what*.** No commented-out code, no `TODO`s left behind.

### Critical anti-patterns (do not do these)

- Adding heavy RAG dependencies (`langchain`/`langchain-postgres`/SQLAlchemy/local sentence-transformers). The vector store talks to CockroachDB through Django's own connection with raw `VECTOR`/`<=>` SQL; extend that, don't replace it with a framework.
- Importing a concrete provider class outside `integrations/` (bypassing the registry).
- Putting prompt text or LLM calls inside views.
- Catching an exception and returning the raw message/stack to the client.
- Adding a dependency to `pyproject.toml` without re-running `uv lock`.

---

## Testing rule (mandatory)

**When you add or change functionality you must (a) run the existing tests and keep them green, and (b) add tests covering the new/changed behaviour.** A change is not done until its tests exist and pass.

- Tests live in each app's `tests.py` (discovered by both pytest and `manage.py test`).
- Cover the **happy path, input-validation/400s, and error/500 handling.** Test behaviour, not implementation.
- **Mock external calls** — patch `get_llm` (and other providers) so tests are fast, deterministic, and offline. Never hit the real Gemini/Groq/S3/email APIs in tests.
- Prefer unit tests for services/`integrations` logic; use DRF `APITestCase`/`APIClient` for endpoints.
- `conftest.py` sets safe provider defaults (`LLM_PROVIDER=noop`, etc.) for the suite.

---

## Security & ops notes

- Never commit real credentials. Production config is environment-driven (see [ARCHITECTURE.md](./ARCHITECTURE.md)).
- The Docker build runs `uv sync --frozen --no-dev`; keep `uv.lock` in sync and don't rely on dev-only packages at runtime.
- `/health/` must stay dependency-light (no model/DB-heavy checks) so Cloud Run health probes are fast.
