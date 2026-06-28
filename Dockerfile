# ============================================================
# Stage 1: Application dependencies
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
# Stage 2: Final production image
# ============================================================
FROM python:3.13-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=core.settings

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
