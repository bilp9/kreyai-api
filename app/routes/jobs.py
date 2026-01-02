# app/routes/jobs.py

from fastapi import APIRouter, HTTPException, UploadFile, File
from datetime import datetime
import uuid

from app.constants import JobStatus, JOB_ID_PREFIX
from app.events.recorder import record_event, get_events
from app.processing.dispatcher import dispatch_job
from app.storage.jobs_store import JOBS

router = APIRouter(prefix="/api", tags=["jobs"])

# -------------------------
# In-memory job store (Phase-1 only)
# -------------------------
#JOBS: dict[str, dict] = {} #removed, and moved to jobs_storePY


# -------------------------
# Create Job
# -------------------------
import random

def generate_verification_code():
    return str(random.randint(100000, 999999))

@router.post("/")
def create_job(email: str):
    job_id = f"{JOB_ID_PREFIX}-{uuid.uuid4().hex[:6].upper()}"

    code = generate_verification_code()

    job = {
        "job_id": job_id,
        "email": email,
        "status": JobStatus.PENDING_VERIFICATION,
        "created_at": datetime.utcnow().isoformat(),
        "verified": False,
        "verification_code": code,
        "attempts": 0,
        "events": [],
    }

    JOBS[job_id] = job

    record_event(job, "job_created", "Job created and awaiting verification")
    print(
    f"""
    =========================
    EMAIL VERIFICATION (DEV)
    =========================
    To: {email}
    Job ID: {job_id}
    Verification Code: {code}
    =========================
    """
    )

    return {
        "job_id": job_id,
        "status": job["status"],
        "created_at": job["created_at"],
    }


# -------------------------
# Verify Email
# -------------------------
@router.post("/verify")
def verify_job(job_id: str, code: str):
    job = JOBS.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["verified"]:
        return {"message": "Already verified"}

    if code != job.get("verification_code"):
        raise HTTPException(status_code=400, detail="Invalid verification code")

    job["verified"] = True
    job["status"] = JobStatus.VERIFIED

    record_event(job, "verified", "Email verification successful")

    return {"message": "Verification successful"}


# -------------------------
# Upload File
# -------------------------
@router.post("/upload")
def upload_file(job_id: str, file: UploadFile = File(...)):
    job = JOBS.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not job["verified"]:
        raise HTTPException(status_code=400, detail="Job not verified")

    job["filename"] = file.filename
    job["status"] = JobStatus.UPLOADED
    job["progress"] = 0
    job["updated_at"] = datetime.utcnow().isoformat()

    record_event(job, "file_uploaded", f"File uploaded: {file.filename}")

    # Queue for processing (Phase-2 worker hook)
    job["status"] = JobStatus.QUEUED
    job["updated_at"] = datetime.utcnow().isoformat()

    record_event(job, "queued", "Job queued for processing")

    dispatch_job(job)

    return {"message": "File uploaded and job queued"}


# -------------------------
# Read Job Status (READ-ONLY)
# -------------------------
@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = JOBS.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "progress": job.get("progress", 0),
        "attempts": job.get("attempts", 0),
        "created_at": job["created_at"],
        "updated_at": job.get("updated_at"),
    }


# -------------------------
# Read Job Events (READ-ONLY)
# -------------------------
@router.get("/jobs/{job_id}/events")
def get_job_events(job_id: str):
    job = JOBS.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job_id,
        "events": get_events(job),
    }
@router.get("/jobs/{job_id}/progress")
def get_job_progress(job_id: str):
    job = JOBS.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "progress": job.get("progress", 0),
        "attempts": job.get("attempts", 0),
    }
