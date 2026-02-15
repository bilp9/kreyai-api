# app/routes/jobs.py

import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, UploadFile, File

from app.constants import JobStatus, JOB_ID_PREFIX
from app.state.firestore_jobs import (
    create_job as fs_create_job,
    get_job as fs_get_job,
    update_job as fs_update_job,
)
from app.processing.dispatcher import dispatch_job
from app.events.recorder import record_event, get_events
from app.storage.backend import get_storage
from app.services.email_service import send_verification_email

router = APIRouter(prefix="/api", tags=["jobs"])


# -------------------------------------------------
# 1️⃣ Create Job
# -------------------------------------------------
@router.post("/")
async def create_job_route(email: str):

    job_id = f"{JOB_ID_PREFIX}-{uuid.uuid4().hex[:6].upper()}"
    code = str(uuid.uuid4().int)[-6:]

    job = {
        "job_id": job_id,
        "email": email,
        "verification_code": code,
        "verified": False,
        "status": JobStatus.PENDING_VERIFICATION,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "attempts": 0,
        "progress": 0,
    }

    # Persist job to Firestore
    fs_create_job(job)

    # Record event (Firestore subcollection)
    record_event(
        job_id,
        "job_created",
        "Awaiting verification",
        JobStatus.PENDING_VERIFICATION,
    )

    # Send verification email asynchronously
    asyncio.create_task(
        send_verification_email(email, job_id, code)
    )

    return {
        "job_id": job_id,
        "status": JobStatus.PENDING_VERIFICATION,
        "created_at": job["created_at"],
    }


# -------------------------------------------------
# 2️⃣ Verify Job
# -------------------------------------------------
@router.post("/verify")
def verify_job_route(job_id: str, code: str):

    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if code != job.get("verification_code"):
        raise HTTPException(400, "Invalid verification code")

    fs_update_job(job_id, {
        "verified": True,
        "status": JobStatus.VERIFIED,
        "updated_at": datetime.utcnow().isoformat(),
    })

    record_event(
        job_id,
        "verified",
        "Email verified",
        JobStatus.VERIFIED,
    )

    return {"message": "Verification successful"}


# -------------------------------------------------
# 3️⃣ Upload File
# -------------------------------------------------
@router.post("/jobs/{job_id}/upload")
def upload_file_route(job_id: str, file: UploadFile = File(...)):

    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if not job.get("verified"):
        raise HTTPException(400, "Job not verified")

    storage = get_storage()

    upload_path = storage.save_upload(
        job_id,
        file.filename,
        file.file,
    )

    # Update Firestore job
    fs_update_job(job_id, {
        "filename": file.filename,
        "upload_path": upload_path,
        "progress": 0,
        "status": JobStatus.QUEUED,
        "updated_at": datetime.utcnow().isoformat(),
    })

    record_event(
        job_id,
        "uploaded",
        f"File uploaded: {file.filename}",
        JobStatus.QUEUED,
    )

    # Dispatch for processing
    dispatch_job(job_id)

    return {"message": "File uploaded and job queued"}


# -------------------------------------------------
# 4️⃣ Get Status
# -------------------------------------------------
@router.get("/jobs/{job_id}")
def get_job_route(job_id: str):

    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    return {
        "job_id": job_id,
        "status": job.get("status"),
        "progress": job.get("progress", 0),
        "attempts": job.get("attempts", 0),
        "created_at": job.get("created_at"),
        "completed_at": job.get("completed_at"),
    }


# -------------------------------------------------
# 5️⃣ Get Events (subcollection)
# -------------------------------------------------
@router.get("/jobs/{job_id}/events")
def get_job_events_route(job_id: str):

    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    return get_events(job_id)


# -------------------------------------------------
# 6️⃣ Download Endpoints
# -------------------------------------------------
@router.get("/jobs/{job_id}/vtt")
def download_vtt_route(job_id: str):

    storage = get_storage()
    url = storage.get_download_url(job_id, "transcript.vtt")
    return {"download_url": url}


@router.get("/jobs/{job_id}/srt")
def download_srt_route(job_id: str):

    storage = get_storage()
    url = storage.get_download_url(job_id, "transcript.srt")
    return {"download_url": url}


@router.get("/jobs/{job_id}/txt")
def download_txt_route(job_id: str):

    storage = get_storage()
    url = storage.get_download_url(job_id, "transcript.txt")
    return {"download_url": url}


@router.get("/jobs/{job_id}/docx")
def download_docx_route(job_id: str):

    storage = get_storage()
    url = storage.get_download_url(job_id, "transcript.docx")
    return {"download_url": url}
