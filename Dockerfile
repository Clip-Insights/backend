# Use a slim Python 3.12 image as the base
FROM python:3.12-slim

# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1
# Ensure Django picks up the correct settings module
ENV DJANGO_SETTINGS_MODULE=core.settings

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libbz2-dev \
    libffi-dev \
    liblzma-dev \
    libncurses5-dev \
    libncursesw5-dev \
    libreadline-dev \
    libssl-dev \
    netcat-traditional \
    tk-dev \
    xz-utils \
    zlib1g-dev \
    ca-certificates \
    libpq-dev \
    pkg-config \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt ./
RUN pip install --upgrade pip \
  && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the Django project into the container
COPY . .

# Download and cache the 'all-MiniLM-L6-v2' model
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Expose port 8000 for the application
EXPOSE 8000

# Run Gunicorn as the production server
CMD ["gunicorn", "--chdir", "/app", "core.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
