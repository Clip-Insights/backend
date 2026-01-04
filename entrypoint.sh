#!/bin/bash
set -e

# 1. Run Migrations (This now happens on Cloud Run, using your Env Vars)
echo "Applying database migrations..."
uv run python manage.py migrate

# 2. Collect Static Files (Optional, but good practice)
echo "Collecting static files..."
uv run python manage.py collectstatic --noinput

# 3. Start the Server
# IMPORTANT: Cloud Run injects a $PORT variable (usually 8080). 
# You must listen on that port, not hardcoded 8000.
echo "Starting server on 0.0.0.0:$PORT..."
uv run python manage.py runserver 0.0.0.0:${PORT:-8000}