from fastapi import APIRouter, HTTPException
from datetime import datetime
import random

from app.models import JobCreateRequest, JobResponse

router = APIRouter()

# --------------------------------------------------
# DEV in-memory job store
# (will be replaced by DB later)
# --------------------------------------------------
JOBS = {}

# --------------------------------------------------
# Canonical job lifecycle states (Phase 2 foundation)
#
# pending_verification
# -> upload_pending
# -> uploaded
# -> processing
# -> completed | failed
# --------------------------------------------------


def generate_job_id() -> str:
    return f"KR-{random.randint(100000, 999999)}"


def generate_verification_code() -> str:
    return str(random.randint(100000, 999999))


@router.post("/", response_model=JobResponse)
def create_job(request: JobCreateRequest):
    """
    Create a new transcription job.
    Phase 1 behavior:
    - Generate job ID
    - Generate verification code
    - Require email verification
    """

    job_id = generate_job_id()
    verification_code = generate_verification_code()
    created_at = datetime.utcnow().isoformat()

    job = {
        "job_id": job_id,
        "email": request.email,
        "status": "pending_verification",
        "verified": False,
        "verification_code": verification_code,
        "created_at": created_at,
    }

    JOBS[job_id] = job

    # DEV email output (temporary)
    print(
        f"""
        =========================
        EMAIL VERIFICATION (DEV)
        =========================
        To: {request.email}
        Job ID: {job_id}
        Verification Code: {verification_code}
        =========================
        """
    )

    return {
        "job_id": job_id,
        "status": job["status"],
        "created_at": job["created_at"],
    }


@router.post("/verify", response_model=JobResponse)
def verify_job(job_id: str, code: str):
    """
    Verify ownership of a job via one-time code.
    On success, job moves to `upload_pending`.
    """

    job = JOBS.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "pending_verification":
        raise HTTPException(
            status_code=400,
            detail="Job already verified or in invalid state",
        )

    if job["verification_code"] != code:
        raise HTTPException(
            status_code=400,
            detail="Invalid verification code",
        )

    # Verification successful
    job["verified"] = True
    job["status"] = "upload_pending"
    job["verified_at"] = datetime.utcnow().isoformat()

    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "created_at": job["created_at"],
    }
