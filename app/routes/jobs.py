from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from datetime import datetime
from typing import Dict
import random
import string
import os

from app.processing.dispatcher import dispatch_job

router = APIRouter()

# -------------------------------------------------------------------
# In-memory job store (Phase 1 only)
# -------------------------------------------------------------------

from app.state.jobs_store import JOBS


UPLOAD_DIR = "app/storage/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def now():
    return datetime.utcnow()

def generate_job_id():
    return "KR-" + "".join(random.choices(string.digits, k=6))

def generate_code():
    return "".join(random.choices(string.digits, k=6))

# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------

@router.post("/")
def create_job(email: str):
    job_id = generate_job_id()
    code = generate_code()

    job = {
        "job_id": job_id,
        "email": email,
        "status": "pending_verification",
        "verification_code": code,
        "created_at": now(),
        "updated_at": now(),
    }

    JOBS[job_id] = job

    # DEV email output (intentional)
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

# -------------------------------------------------------------------

@router.post("/verify")
def verify_job(
    job_id: str = Query(...),
    code: str = Query(...)
):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "pending_verification":
        raise HTTPException(status_code=400, detail="Job already verified")

    if job["verification_code"] != code:
        raise HTTPException(status_code=400, detail="Invalid verification code")

    job["status"] = "verified"
    job["updated_at"] = now()

    return {
        "job_id": job_id,
        "status": job["status"],
        "verified_at": job["updated_at"],
    }

# -------------------------------------------------------------------

@router.post("/upload")
def upload_file(
    job_id: str = Query(...),
    file: UploadFile = File(...)
):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "verified":
        raise HTTPException(
            status_code=400,
            detail="Job must be verified before upload",
        )

    file_path = os.path.join(UPLOAD_DIR, f"{job_id}_{file.filename}")

    with open(file_path, "wb") as f:
        f.write(file.file.read())

    job["file_path"] = file_path
    job["status"] = "queued"
    job["updated_at"] = now()

    # Phase-2 groundwork hook
    dispatch_job(job_id)

    return {
        "job_id": job_id,
        "status": job["status"],
        "uploaded_at": job["updated_at"],
    }

# -------------------------------------------------------------------

@router.get("/jobs/{job_id}")
def get_job_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "completed_at": job.get("completed_at"),
    }
