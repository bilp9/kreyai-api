from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime
from typing import Optional, Dict, Any

# FastAPI
from fastapi import (
    APIRouter,
    HTTPException,
    UploadFile,
    File,
    Request,
    Body,
)
from fastapi.responses import RedirectResponse

# Internal app modules
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
from app.security.job_tokens import (
    JobTokenConfig,
    mint_job_token,
    verify_job_token,
    TokenExpired,
    TokenInvalid,
)

router = APIRouter(prefix="/api", tags=["jobs"])
# -------------------------------------------------
# Token Helpers
# -------------------------------------------------

def _token_cfg() -> JobTokenConfig:
    secret = os.getenv("JOB_TOKEN_SECRET", "")
    ttl = int(os.getenv("JOB_TOKEN_TTL_SECONDS", str(7 * 24 * 3600)))
    return JobTokenConfig(secret=secret, ttl_seconds=ttl)


def _require_token(request: Request, job_id: str) -> None:
    token = request.query_params.get("t") or request.headers.get("X-Job-Token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing access token.")

    try:
        verify_job_token(_token_cfg(), token=token, job_id=job_id)
    except TokenExpired:
        raise HTTPException(status_code=410, detail="Access expired.")
    except TokenInvalid:
        raise HTTPException(status_code=401, detail="Invalid access token.")


# -------------------------------------------------
# 1️⃣ Create Job
# -------------------------------------------------


@router.post("/")
async def create_job_route(
    email: str = Body(...),
    language: str = Body("en"),
    accepted_terms: bool = Body(False),
):
    if not accepted_terms:
        raise HTTPException(
            status_code=400,
            detail="You must accept the Terms of Service."
        )

    job_id = f"{JOB_ID_PREFIX}-{uuid.uuid4().hex[:6].upper()}"
    code = str(uuid.uuid4().int)[-6:]

    job = {
        "job_id": job_id,
        "email": email,
        "language": language,
        "accepted_terms": True,
        "terms_accepted_at": datetime.utcnow().isoformat(),
        "verification_code": code,
        "verified": False,
        "status": JobStatus.PENDING_VERIFICATION,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "attempts": 0,
        "progress": 0,
    }

    fs_create_job(job)
    record_event(job_id, "job_created", "Awaiting verification", JobStatus.PENDING_VERIFICATION)
    asyncio.create_task(send_verification_email(email, job_id, code))

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

    if job.get("verified"):
        token = mint_job_token(_token_cfg(), job_id=job_id)
        return {"message": "Already verified", "access_token": token}

    fs_update_job(
        job_id,
        {
            "verified": True,
            "status": JobStatus.VERIFIED,
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

    record_event(job_id, "verified", "Email verified", JobStatus.VERIFIED)

    token = mint_job_token(_token_cfg(), job_id=job_id)

    return {"message": "Verification successful", "access_token": token}


# -------------------------------------------------
# 3️⃣ Upload (Legacy)
# -------------------------------------------------

@router.post("/jobs/{job_id}/upload")
def upload_file_route(job_id: str, request: Request, file: UploadFile = File(...)):
    _require_token(request, job_id)

    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    storage = get_storage()
    upload_path = storage.save_upload(job_id, file.filename, file.file)

    fs_update_job(
        job_id,
        {
            "filename": file.filename,
            "upload_path": upload_path,
            "file_path": upload_path,
            "progress": 0,
            "status": JobStatus.QUEUED,
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

    record_event(job_id, "uploaded", f"File uploaded: {file.filename}", JobStatus.QUEUED)
    dispatch_job(job_id)

    return {"message": "File uploaded and job queued"}


# -------------------------------------------------
# 4️⃣ Get Status (Token Protected)
# -------------------------------------------------

@router.get("/jobs/{job_id}")
def get_job_route(job_id: str, request: Request):
    _require_token(request, job_id)

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
# 5️⃣ Get Events (Token Protected)
# -------------------------------------------------

@router.get("/jobs/{job_id}/events")
def get_job_events_route(job_id: str, request: Request):
    _require_token(request, job_id)

    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    return get_events(job_id)


# -------------------------------------------------
# 6️⃣ Download Endpoints (Redirect)
# -------------------------------------------------

@router.get("/jobs/{job_id}/vtt")
def download_vtt_route(job_id: str, request: Request):
    _require_token(request, job_id)
    url = get_storage().get_download_url(job_id, "transcript.vtt")
    return RedirectResponse(url, status_code=302)


@router.get("/jobs/{job_id}/srt")
def download_srt_route(job_id: str, request: Request):
    _require_token(request, job_id)
    url = get_storage().get_download_url(job_id, "transcript.srt")
    return RedirectResponse(url, status_code=302)


@router.get("/jobs/{job_id}/txt")
def download_txt_route(job_id: str, request: Request):
    _require_token(request, job_id)
    url = get_storage().get_download_url(job_id, "transcript.txt")
    return RedirectResponse(url, status_code=302)


@router.get("/jobs/{job_id}/docx")
def download_docx_route(job_id: str, request: Request):
    _require_token(request, job_id)
    url = get_storage().get_download_url(job_id, "transcript.docx")
    return RedirectResponse(url, status_code=302)