FROM python:3.12-slim

# Set the working directory to /app
WORKDIR /app

# Install system dependencies
# ffmpeg is essential for processing .m4a and other audio formats
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

# --- PRE-DOWNLOAD WHISPER MODEL ---
# Baking the model into the image prevents runtime timeouts during scaling
RUN mkdir -p /app/models/base && \
    wget -q https://huggingface.co/Systran/faster-whisper-base/resolve/main/model.bin -O /app/models/base/model.bin && \
    wget -q https://huggingface.co/Systran/faster-whisper-base/resolve/main/config.json -O /app/models/base/config.json && \
    wget -q https://huggingface.co/Systran/faster-whisper-base/resolve/main/vocabulary.txt -O /app/models/base/vocabulary.txt && \
    wget -q https://huggingface.co/Systran/faster-whisper-base/resolve/main/tokenizer.json -O /app/models/base/tokenizer.json

# Copy application code and data files
# Ensure the 'data' directory containing 'api_keys.json' exists locally
COPY app ./app
COPY data ./data
COPY docs ./docs

# --- STORAGE AND PATH SETUP ---
# Create storage directories with write permissions for the app
RUN mkdir -p /app/app/storage && chmod 777 /app/app/storage
RUN mkdir -p /app/storage && chmod 777 /app/storage
RUN mkdir -p /app/data && chmod 777 /app/data

# Environment Variables
ENV PORT=8080
ENV KREYAI_ENV=cloudrun
ENV WHISPER_MODEL_PATH=/app/models/base
ENV STORAGE_PATH=/app/app/storage
ENV PYTHONUNBUFFERED=1

# CRITICAL: This path must match what app/models/user.py looks for
ENV API_KEYS_FILE=/app/data/api_keys.json

EXPOSE 8080

# Use Gunicorn with Uvicorn workers for production stability
CMD gunicorn app.main:app \
    --bind 0.0.0.0:${PORT} \
    --workers 1 \
    --worker-class uvicorn.workers.UvicornWorker \
    --timeout 0