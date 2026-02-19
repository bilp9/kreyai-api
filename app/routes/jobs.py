# app/routes/jobs.py

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict

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


def _now() -> str:
    return datetime.utcnow().isoformat()


def _new_job_id() -> str:
    return f"{JOB_ID_PREFIX}-{uuid.uuid4().hex[:6].upper()}"


def _new_code() -> str:
    # 6-digit code
    return str(uuid.uuid4().int)[-6:]


# -------------------------------------------------
# 1) Create Job
# -------------------------------------------------
@router.post("/")
async def create_job_route(email: str) -> Dict[str, Any]:
    job_id = _new_job_id()
    code = _new_code()

    job = {
        "job_id": job_id,
        "email": email,
        "verification_code": code,
        "verified": False,
        "status": JobStatus.PENDING_VERIFICATION.value,
        "created_at": _now(),
        "updated_at": _now(),
        "attempts": 0,
        "progress": 0,
    }

    fs_create_job(job)

    record_event(
        job_id=job_id,
        event_type="job_created",
        message="Awaiting verification",
        status=JobStatus.PENDING_VERIFICATION.value,
    )

    # Fire-and-forget email (don’t block request)
    asyncio.create_task(send_verification_email(email, job_id, code))

    return {
        "job_id": job_id,
        "status": JobStatus.PENDING_VERIFICATION.value,
        "created_at": job["created_at"],
    }


# -------------------------------------------------
# 2) Verify Job
# -------------------------------------------------
@router.post("/verify")
def verify_job_route(job_id: str, code: str) -> Dict[str, str]:
    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if code != job.get("verification_code"):
        raise HTTPException(status_code=400, detail="Invalid verification code")

    fs_update_job(
        job_id,
        {
            "verified": True,
            "status": JobStatus.VERIFIED.value,
            "updated_at": _now(),
        },
    )

    record_event(
        job_id=job_id,
        event_type="verified",
        message="Email verified",
        status=JobStatus.VERIFIED.value,
    )

    return {"message": "Verification successful"}


# -------------------------------------------------
# 3) Upload File (PRODUCTION: GCS)
# -------------------------------------------------
@router.post("/jobs/{job_id}/upload")
async def upload_file_route(job_id: str, file: UploadFile = File(...)) -> Dict[str, str]:
    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not job.get("verified"):
        raise HTTPException(status_code=400, detail="Job not verified")

    storage = get_storage()

    filename = file.filename or "upload.bin"
    blob_path = storage.upload_blob_path(job_id, filename)

    try:
        data = await file.read()
        gcs_uri = storage.upload_bytes(
            blob_path=blob_path,
            data=data,
            content_type=file.content_type,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

    fs_update_job(
        job_id,
        {
            "filename": filename,
            "upload_path": gcs_uri,  # IMPORTANT: store gs://... not a relative path
            "progress": 0,
            "status": JobStatus.QUEUED.value,
            "updated_at": _now(),
        },
    )

    record_event(
        job_id=job_id,
        event_type="uploaded",
        message=f"File uploaded: {filename}",
        status=JobStatus.QUEUED.value,
    )

    # Trigger worker (Cloud Tasks / PubSub / Scheduler — whatever dispatcher implements)
    dispatch_job(job_id)

    return {"message": "File uploaded and job queued"}


# -------------------------------------------------
# 4) Get Status
# -------------------------------------------------
@router.get("/jobs/{job_id}")
def get_job_route(job_id: str) -> Dict[str, Any]:
    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job_id,
        "status": job.get("status"),
        "progress": job.get("progress", 0),
        "attempts": job.get("attempts", 0),
        "created_at": job.get("created_at"),
        "completed_at": job.get("completed_at"),
    }


# -------------------------------------------------
# 5) Get Events
# -------------------------------------------------
@router.get("/jobs/{job_id}/events")
def get_job_events_route(job_id: str):
    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return get_events(job_id)


# -------------------------------------------------
# 6) Download Endpoints (Signed URLs)
# -------------------------------------------------
def _download_url(job_id: str, filename: str) -> Dict[str, str]:
    storage = get_storage()
    try:
        url = storage.get_download_url(job_id, filename)
        return {"download_url": url}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create download URL: {e}")


@router.get("/jobs/{job_id}/vtt")
def download_vtt_route(job_id: str):
    return _download_url(job_id, "transcript.vtt")


@router.get("/jobs/{job_id}/srt")
def download_srt_route(job_id: str):
    return _download_url(job_id, "transcript.srt")


@router.get("/jobs/{job_id}/txt")
def download_txt_route(job_id: str):
    return _download_url(job_id, "transcript.txt")


@router.get("/jobs/{job_id}/docx")
def download_docx_route(job_id: str):
    return _download_url(job_id, "transcript.docx")
