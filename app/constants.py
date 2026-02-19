"""
Kreyai — Global Constants

System-wide limits, enums, and flags.
Safe to import anywhere (routes, services, workers).

Phase-1 compatible
Phase-2 ready
Phase-3 ready (local durable queue)
"""

from enum import Enum


# =========================
# Job Lifecycle
# =========================

class JobStatus(str, Enum):
    """
    Inheriting from 'str' ensures JobStatus.QUEUED == "queued"
    This allows Firestore queries to match correctly against string data.
    """
    PENDING_VERIFICATION = "pending_verification"
    VERIFIED = "verified"
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


# =========================
# File & Upload Limits
# =========================

# Maximum upload size (target: 1–2 GB)
MAX_UPLOAD_SIZE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB

# Allowed file extensions (audio + video)
ALLOWED_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg",
    ".mp4", ".mov", ".mkv", ".webm",
}


# =========================
# Retention Policy
# =========================

DEFAULT_RETENTION_DAYS = 7
RETENTION_OPTIONS_DAYS = {0, 1, 7, 30}


# =========================
# Verification
# =========================

VERIFICATION_CODE_LENGTH = 6
VERIFICATION_CODE_TTL_MINUTES = 15


# =========================
# Feature Flags
# =========================

FEATURE_DIARIZATION_ENABLED = True
FEATURE_SUBTITLES_ENABLED = True
FEATURE_MULTI_LANGUAGE_ENABLED = True


# =========================
# Output Formats
# =========================

TEXT_OUTPUT_FORMATS = {"txt", "json"}
SUBTITLE_FORMATS = {"srt", "vtt"}


# =========================
# Misc
# =========================

JOB_ID_PREFIX = "KR"


# =========================
# Phase-3A: Local Durable Queue
# =========================

# SQLite db file for queue durability
QUEUE_DB_PATH = "app/storage/queue/queue.db"

# How long a lease lasts before the job can be reclaimed
QUEUE_LEASE_SECONDS = 60

# Maximum number of times a job can be leased/attempted at the queue level
QUEUE_MAX_ATTEMPTS = 3

# Worker polling interval (used later in Phase-3A worker loop)
WORKER_POLL_SECONDS = 1.0

# =========================
# Phase-3A: Worker + Retry + Timeout
# =========================

# Per-attempt timeout while processing a job
PROCESS_ATTEMPT_TIMEOUT_SECONDS = 60 * 30  # 30 minutes


# How many processing attempts before we mark the job FAILED permanently
PROCESS_MAX_ATTEMPTS = 3