"""
PHASE 1 API — FROZEN CONTRACT

This file defines the complete Phase 1 job lifecycle for Kreyai.

Rules:
- No new fields may be added in Phase 1
- No request/response schema changes
- Only comments, validation, and bug fixes are allowed
- Any functional expansion must occur in Phase 2

Phase 1 priorities:
- Safety
- Clarity
- Supportability
"""

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, EmailStr
from datetime import datetime
import random

router = APIRouter(prefix="/api", tags=["jobs"])

# ============================================================
# Phase 1 Canonical Job States (DO NOT MODIFY)
# ============================================================

PHASE1_JOB_STATES = {
    "created",               # Job created, awaiting verification
    "pending_verification",  # Verification email sent
    "verified",              # Email verified
    "uploaded",              # File uploaded
    "processing",            # Transcription in progress (manual/dev)
    "completed",             # Transcript ready
    "failed",                # Unrecoverable error
}

# ============================================================
# In-memory store (Phase 1 only)
# ============================================================

# NOTE:
# This is intentionally in-memory for Phase 1.
# Persistence will be introduced in Phase 2.
jobs_db: dict[str, dict] = {}

# ============================================================
# Models (Frozen)
# ============================================================

class JobCreateRequest(BaseModel):
    email: EmailStr


class JobResponse(BaseModel):
    job_id: str
    status: str
    created_at: datetime


# ============================================================
# Helpers
# ============================================================

def generate_job_id() -> str:
    return f"KR-{random.randint(100000, 999999)}"


def generate_verification_code() -> str:
    return f"{random.randint(100000, 999999)}"


def send_verification_email(email: str, job_id: str, code: str) -> None:
    """
    Phase 1 email delivery (DEV MODE).

    In production, this will be replaced by a transactional
    email provider. For now, output is logged for verification.
    """
    print(f"""
=========================
EMAIL VERIFICATION (DEV)
=========================
To: {email}
Job ID: {job_id}
Verification Code: {code}
=========================
""")


# ============================================================
# Endpoints
# ============================================================

@router.post("/", response_model=JobResponse)
def create_job(payload: JobCreateRequest):
    """
    Create a new transcription job.

    Phase 1 notes:
    - Email is required to establish ownership
    - Job cannot proceed without verification
    - Retention policy begins at creation time (7 days)
    """

    job_id = generate_job_id()
    verification_code = generate_verification_code()
    now = datetime.utcnow()

    jobs_db[job_id] = {
        "job_id": job_id,
        "email": payload.email,
        "verification_code": verification_code,
        "status": "pending_verification",
        "created_at": now,
        "file_uploaded": False,
    }

    send_verification_email(payload.email, job_id, verification_code)

    return JobResponse(
        job_id=job_id,
        status="pending_verification",
        created_at=now,
    )


@router.post("/verify")
def verify_job(
    job_id: str = Query(...),
    code: str = Query(...)
):
    """
    Verify ownership of a job via email code.

    Rules:
    - Verification can only happen once
    - Verified jobs unlock file upload
    """

    job = jobs_db.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] == "verified":
        raise HTTPException(status_code=400, detail="Job already verified")

    if code != job["verification_code"]:
        raise HTTPException(status_code=400, detail="Invalid verification code")

    job["status"] = "verified"
    return {"message": "Job verified successfully"}


@router.post("/upload")
def upload_file(
    job_id: str = Query(...),
    file: UploadFile = File(...)
):
    """
    Upload an audio or video file.

    Guards:
    - Job must be verified
    - Only one upload allowed in Phase 1
    """

    job = jobs_db.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "verified":
        raise HTTPException(
            status_code=400,
            detail="File upload is only allowed after email verification"
        )

    if job["file_uploaded"]:
        raise HTTPException(
            status_code=400,
            detail="File already uploaded for this job"
        )

    # NOTE:
    # File is not persisted in Phase 1.
    # Storage integration occurs in Phase 2.
    job["file_uploaded"] = True
    job["status"] = "uploaded"

    return {"message": "File uploaded successfully"}


@router.get("/jobs/status", response_model=JobResponse)
def job_status(job_id: str = Query(...)):
    """
    Read-only job status endpoint.

    Used by:
    - Frontend polling
    - Support inquiries
    - Phase 2 UI

    No mutation allowed.
    """

    job = jobs_db.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobResponse(
        job_id=job["job_id"],
        status=job["status"],
        created_at=job["created_at"],
    )
