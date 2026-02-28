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

# Pre-download Whisper Model
RUN mkdir -p /app/models/base && \
    wget -q https://huggingface.co/Systran/faster-whisper-base/resolve/main/model.bin -O /app/models/base/model.bin && \
    wget -q https://huggingface.co/Systran/faster-whisper-base/resolve/main/config.json -O /app/models/base/config.json && \
    wget -q https://huggingface.co/Systran/faster-whisper-base/resolve/main/vocabulary.txt -O /app/models/base/vocabulary.txt && \
    wget -q https://huggingface.co/Systran/faster-whisper-base/resolve/main/tokenizer.json -O /app/models/base/tokenizer.json

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
ENV PYTHONUNBUFFERED=1
ENV API_KEYS_FILE=/app/data/api_keys.json

EXPOSE 8080

CMD gunicorn app.main:app \
    --bind 0.0.0.0:${PORT} \
    --workers 1 \
    --worker-class uvicorn.workers.UvicornWorker \
    --timeout 0