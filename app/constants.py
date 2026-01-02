# app/constants.py

from enum import Enum

class JobStatus(str, Enum):
    PENDING_VERIFICATION = "pending_verification"
    VERIFIED = "verified"
    UPLOADED = "uploaded"
    QUEUED = "queued"          # ✅ THIS WAS MISSING
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"



# =========================
# Upload Guardrails
# =========================

# Max upload size (bytes)
# Phase 1 / early Phase 2: 1 GB
MAX_UPLOAD_SIZE_BYTES = 1 * 1024 * 1024 * 1024  # 1GB

# Allowed extensions (lowercase)
ALLOWED_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".mp4",
    ".mov",
    ".aac",
    ".flac",
}
# =========================
# Job ID
# =========================

JOB_ID_PREFIX = "KR"

# =========================
# Processing Behavior
# =========================

MAX_PROCESSING_SECONDS = 20          # hard timeout
MAX_RETRY_ATTEMPTS = 2               # controlled retries
PROGRESS_STEP_SECONDS = 1            # progress tick

# =========================
# Processing / Retry Logic
# =========================

# Max time allowed for a single processing attempt
JOB_ATTEMPT_TIMEOUT_SECONDS = 300  # 5 minutes (safe Phase-2 default)

# Max retry attempts before marking job as failed
MAX_JOB_ATTEMPTS = 3

# =========================
# Retention (Phase 1 policy)
# =========================

DEFAULT_RETENTION_DAYS = 7
