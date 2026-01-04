#!/bin/bash
set -e

echo "🚀 Starting Deployment Script..."

# 1. Run Migrations
echo "📦 Applying database migrations..."
uv run python manage.py migrate

# 2. Collect Static Files
echo "🎨 Collecting static files..."
uv run python manage.py collectstatic --noinput

# 3. Start Uvicorn Server
# Cloud Run injects the $PORT variable (usually 8080).
# We default to 8080 if the variable is missing.
echo "🔥 Starting Uvicorn on 0.0.0.0:${PORT:-8080}..."

exec uv run uvicorn clip_insights_be.asgi:application --host 0.0.0.0 --port ${PORT:-8080} --workers 1