#!/bin/sh
set -e

echo "🚀 Starting Application..."

# Verify pre-baked model exists
MODEL_PATH="/app/textutils/embeddings/all-MiniLM-L6-v2"
if [ -d "$MODEL_PATH" ]; then
    echo "✅ Pre-baked embedding model found: $MODEL_PATH"
else
    echo "⚠️  Warning: Pre-baked model not found at $MODEL_PATH"
    echo "   Model will be downloaded on first use (cold start impact)"
fi

# Verify CockroachDB certificate
DB_CERT_PATH="${DATABASE_CERT_PATH:-/root/.postgresql/root.crt}"
if [ -f "$DB_CERT_PATH" ]; then
    echo "✅ CockroachDB certificate found"
else
    echo "❌ Error: CockroachDB certificate not found at $DB_CERT_PATH"
    exit 1
fi

# Start Uvicorn Server
# Cloud Run injects the $PORT variable (usually 8080).
echo "🔥 Starting Uvicorn on 0.0.0.0:${PORT:-8080}..."

exec uvicorn core.asgi:application \
    --host 0.0.0.0 \
    --port ${PORT:-8080} \
    --workers 1 \
    --timeout-keep-alive 300 \
    --timeout-graceful-shutdown 10 \
    --log-level warning
