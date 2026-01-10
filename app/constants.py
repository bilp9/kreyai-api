"""
Kreyai — Global Constants

Single source of truth for:
- Job lifecycle
- Processing limits
- Retry + timeout policy
- Feature flags

Phase-1 compatible
Phase-2 (A/B/C) stable
"""

from enum import Enum


# =========================
# Job Lifecycle
# =========================

class JobStatus(str, Enum):
    PENDING_VERIFICATION = "pending_verification"
    VERIFIED = "verified"
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


# =========================
# Job ID
# =========================

JOB_ID_PREFIX = "KR"


# =========================
# Retry + Timeout Policy
# =========================

# Max number of processing attempts
MAX_JOB_ATTEMPTS = 3

# Per-attempt processing timeout (seconds)
JOB_ATTEMPT_TIMEOUT_SECONDS = 30


# =========================
# Progress Simulation
# =========================

# Deterministic progress steps for UI + testing
PROGRESS_STEPS = [10, 30, 60, 90, 100]


# =========================
# File & Upload Limits
# =========================

# Phase-2 target: large media support
MAX_UPLOAD_SIZE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB

ALLOWED_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
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
