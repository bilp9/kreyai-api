# app/constants.py
from enum import Enum

class JobStatus(str, Enum):
    PENDING_VERIFICATION = "pending_verification"
    VERIFIED = "verified"
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"

JOB_ID_PREFIX = "KR"

# Phase-2A execution rules
MAX_JOB_ATTEMPTS = 3
JOB_ATTEMPT_TIMEOUT_SECONDS = 20   # simulation timeout
PROGRESS_STEP_SECONDS = 1
PROGRESS_INCREMENT = 10            # 10% per step
