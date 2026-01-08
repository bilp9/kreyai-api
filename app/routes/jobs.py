# app/routes/jobs.py
from fastapi import APIRouter, HTTPException, UploadFile, File
from datetime import datetime
import uuid

from app.constants import JobStatus, JOB_ID_PREFIX
from app.state.jobs_store import JOBS
from app.processing.dispatcher import dispatch_job
from app.events.recorder import record_event, get_events

router = APIRouter(prefix="/api", tags=["jobs"])


@router.post("/")
def create_job(email: str):
    job_id = f"{JOB_ID_PREFIX}-{uuid.uuid4().hex[:6].upper()}"
    code = str(uuid.uuid4().int)[-6:]

    job = {
        "job_id": job_id,
        "email": email,
        "verification_code": code,
        "verified": False,
        "status": JobStatus.PENDING_VERIFICATION,
        "created_at": datetime.utcnow().isoformat(),
        "attempts": 0,
        "progress": 0,
        "events": [],
    }

    JOBS[job_id] = job

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

    record_event(job, "job_created", "Awaiting verification")

    return {
        "job_id": job_id,
        "status": job["status"],
        "created_at": job["created_at"],
    }


@router.post("/verify")
def verify_job(job_id: str, code: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if job["verified"]:
        return {"message": "Already verified"}

    if code != job["verification_code"]:
        raise HTTPException(400, "Invalid verification code")

    job["verified"] = True
    job["status"] = JobStatus.VERIFIED

    record_event(job, "verified", "Email verified")

    return {"message": "Verification successful"}


@router.post("/upload")
def upload_file(job_id: str, file: UploadFile = File(...)):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if not job["verified"]:
        raise HTTPException(400, "Job not verified")

    job["filename"] = file.filename
    job["status"] = JobStatus.QUEUED
    job["progress"] = 0

    record_event(job, "uploaded", f"File uploaded: {file.filename}")
    record_event(job, "queued", "Job queued for processing")

    dispatch_job(job_id)

    return {"message": "File uploaded and processing started"}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "attempts": job["attempts"],
        "progress": job["progress"],
    }


@router.get("/jobs/{job_id}/progress")
def get_progress(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    return {
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
    }


@router.get("/jobs/{job_id}/events")
def get_job_events(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    return get_events(job)
