# /Users/billyp/projects/kreyai-api/Dockerfile

FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    libgomp1 \
    wget \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip \
  && pip install --no-cache-dir -r requirements.txt \
  && pip install --no-cache-dir gunicorn

# Pre-download Whisper models using huggingface_hub for more reliable large-file fetches.
RUN python -c "from huggingface_hub import snapshot_download; \
snapshot_download(repo_id='Systran/faster-whisper-base', local_dir='/app/models/base', local_dir_use_symlinks=False); \
snapshot_download(repo_id='Systran/faster-whisper-large-v3', local_dir='/app/models/large-v3', local_dir_use_symlinks=False)"

# --- IMPROVED COPY STRATEGY ---
# Copy everything into /app. This preserves the root package structure.
COPY . .

# CRITICAL: Ensure Python treats directories as packages
# This fixes the ModuleNotFoundError: No module named 'app.storage.backend'
RUN touch app/__init__.py app/storage/__init__.py app/processing/__init__.py app/workers/__init__.py

# Environment Variables
ENV PORT=8080
ENV KREYAI_ENV=cloudrun
ENV PYTHONPATH=/app
ENV WHISPER_MODEL_PATH=/app/models/base
ENV WHISPER_MODEL_PATH_HT=/app/models/large-v3
ENV PYTHONUNBUFFERED=1
ENV API_KEYS_FILE=/app/data/api_keys.json

EXPOSE 8080

CMD gunicorn app.main:app \
    --bind 0.0.0.0:${PORT} \
    --workers 1 \
    --worker-class uvicorn.workers.UvicornWorker \
    --timeout 0
