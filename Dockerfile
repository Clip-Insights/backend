# ============================================================
# Build argument for model version pinning
# This ensures the model layer is ONLY rebuilt when version changes
# ============================================================
ARG EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2
ARG EMBEDDING_MODEL_REVISION=main

# ============================================================
# Stage 1: Download and cache embedding models (isolated layer)
# ============================================================
FROM python:3.13-slim AS model-downloader

ARG EMBEDDING_MODEL_NAME
ARG EMBEDDING_MODEL_REVISION

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/model-cache \
    TRANSFORMERS_CACHE=/model-cache \
    SENTENCE_TRANSFORMERS_HOME=/model-cache

# Install minimal system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
RUN pip install --no-cache-dir uv

# Create virtual environment for model download
RUN uv venv /model-venv
ENV PATH="/model-venv/bin:$PATH"

# Install ONLY the packages needed for model download
# This layer is cached unless the ARG values change
RUN uv pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    sentence-transformers>=5.2.0 \
    torch>=2.9.1 \
    transformers>=4.51.2 \
    huggingface-hub>=0.30.2

# KEY OPTIMIZATION: Download model with pinned version
# This layer is ONLY rebuilt when EMBEDDING_MODEL_NAME or REVISION changes
RUN python -c "import os; os.environ['HF_HOME'] = '/model-cache'; from sentence_transformers import SentenceTransformer; model = SentenceTransformer('${EMBEDDING_MODEL_NAME}', revision='${EMBEDDING_MODEL_REVISION}'); model.save('/model-cache/${EMBEDDING_MODEL_NAME}'); print('Model ${EMBEDDING_MODEL_NAME} downloaded and saved successfully')"

# Verify model files exist
RUN test -d /model-cache/${EMBEDDING_MODEL_NAME} && \
    test -f /model-cache/${EMBEDDING_MODEL_NAME}/config.json && \
    echo "Model integrity verified" || \
    (echo "Model download failed!" && exit 1)

# ============================================================
# Stage 2: Application dependencies
# ============================================================
FROM python:3.13-slim AS app-deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Download CockroachDB certificate
RUN curl --create-dirs -o /root/.postgresql/root.crt \
    "https://cockroachlabs.cloud/clusters/8b06e7de-f0ef-468b-a189-5914654f3c10/cert"

# Install uv
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy dependency files FIRST (cache layer - changes infrequently)
COPY pyproject.toml uv.lock ./

# Create virtual environment and install all dependencies
RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN uv sync --frozen --no-dev

# ============================================================
# Stage 3: Final production image
# ============================================================
FROM python:3.13-slim AS production

ARG EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=core.settings \
    HF_HOME=/app/videos/embeddings \
    TRANSFORMERS_CACHE=/app/videos/embeddings \
    SENTENCE_TRANSFORMERS_HOME=/app/videos/embeddings

# Install minimal runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy virtual environment from app-deps stage
COPY --from=app-deps /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy CockroachDB certificate
COPY --from=app-deps /root/.postgresql/root.crt /root/.postgresql/root.crt

# KEY OPTIMIZATION: Copy pre-baked model from isolated stage
# This creates a deterministic, cacheable layer
COPY --from=model-downloader /model-cache/${EMBEDDING_MODEL_NAME} /app/videos/embeddings/${EMBEDDING_MODEL_NAME}

# Copy application code (this layer changes frequently - LAST)
COPY . .

# Pre-collect static files during build (not at runtime)
RUN python manage.py collectstatic --noinput --clear || echo "Static collection skipped"

# Copy optimized entrypoint
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser && \
    chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE ${PORT:-8080}

# Health check for Cloud Run
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.getenv(\"PORT\", \"8080\")}/health/', timeout=3)" || exit 1

# Use entrypoint
CMD ["/app/entrypoint.sh"]
