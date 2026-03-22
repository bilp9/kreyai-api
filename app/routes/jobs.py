# app/routes/jobs.py

from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.config import get_language_label, get_public_api_version, get_public_language_options, get_public_supported_language_codes
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
from app.transcription.engine import normalize_language_code
from app.security.job_tokens import (
    JobTokenConfig,
    mint_job_token,
    verify_job_token,
    TokenExpired,
    TokenInvalid,
)

router = APIRouter(prefix="/api", tags=["jobs"])


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_requested_language(language: str) -> str:
    raw_language = str(language or "").strip()
    normalized_language = normalize_language_code(raw_language)

    if raw_language.lower() == "auto":
        return "auto"

    if normalized_language is None:
        supported = ", ".join(get_public_supported_language_codes())
        raise HTTPException(
            status_code=400,
            detail=(
                f"Requested language is not supported in API v{get_public_api_version()}. "
                f"Supported languages: {supported}, auto."
            ),
        )

    if normalized_language not in get_public_supported_language_codes():
        supported = ", ".join(get_public_supported_language_codes())
        raise HTTPException(
            status_code=400,
            detail=(
                f"Requested language is not supported in API v{get_public_api_version()}. "
                f"Supported languages: {supported}, auto."
            ),
        )

    return normalized_language


@router.get("/public-config")
def get_public_config():
    return {
        "api_version": get_public_api_version(),
        "languages": [
            {"code": code, "label": get_language_label(code)}
            for code in get_public_language_options()
        ],
        "default_language": "auto",
    }


# -------------------------------------------------
# Token Helpers
# -------------------------------------------------

def _token_cfg() -> JobTokenConfig:
    secret = os.getenv("JOB_TOKEN_SECRET", "")
    ttl = int(os.getenv("JOB_TOKEN_TTL_SECONDS", str(7 * 24 * 3600)))
    if len(secret) < 16:
        raise HTTPException(
            status_code=503,
            detail="Job access tokens are not configured.",
        )
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
    background_tasks: BackgroundTasks,
    response: Response,
    email: str = Body(...),
    language: str = Body("auto"),
    accepted_terms: bool = Body(False),
):
    started_at = time.perf_counter()
    language = _normalize_requested_language(language)

    if not accepted_terms:
        raise HTTPException(
            status_code=400,
            detail="You must accept the Terms of Service.",
        )

    job_id = f"{JOB_ID_PREFIX}-{uuid.uuid4().hex[:6].upper()}"
    code = str(uuid.uuid4().int)[-6:]

    job = {
        "job_id": job_id,
        "email": email,
        "language": language,
        "accepted_terms": True,
        "terms_accepted_at": _utcnow_iso(),
        "verification_code": code,
        "verified": False,
        "status": JobStatus.PENDING_VERIFICATION,
        "created_at": _utcnow_iso(),
        "updated_at": _utcnow_iso(),
        "progress": 0,
    }

    await asyncio.to_thread(fs_create_job, job)
    background_tasks.add_task(
        record_event,
        job_id,
        "job_created",
        "Awaiting verification",
        JobStatus.PENDING_VERIFICATION,
    )
    background_tasks.add_task(send_verification_email, email, job_id, code)

    response.headers["Server-Timing"] = (
        f"create_job;dur={(time.perf_counter() - started_at) * 1000:.1f}"
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

    fs_update_job(
        job_id,
        {
            "verified": True,
            "status": JobStatus.VERIFIED,
            "updated_at": _utcnow_iso(),
        },
    )

    record_event(job_id, "verified", "Email verified", JobStatus.VERIFIED)

    token = mint_job_token(_token_cfg(), job_id=job_id)

    return {"access_token": token}


# -------------------------------------------------
# 3️⃣ Create Resumable Upload Session
# -------------------------------------------------

@router.post("/jobs/{job_id}/upload-url")
def create_upload_url(job_id: str, request: Request):
    _require_token(request, job_id)

    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    filename = request.query_params.get("filename")
    content_type = request.query_params.get("content_type")

    if not filename:
        raise HTTPException(400, "Missing filename")

    storage = get_storage()
    upload_path = storage.upload_blob_path(job_id, filename)

    signed_start_url = storage.generate_resumable_start_url(
        blob_path=upload_path,
        content_type=content_type or "application/octet-stream",
    )

    return {
        "signed_start_url": signed_start_url,
        "upload_path": upload_path,
    }


# -------------------------------------------------
# 4️⃣ Finalize Upload (FIXED — Uses JSON Body)
# -------------------------------------------------

class FinalizeUploadRequest(BaseModel):
    file_path: str
    size_bytes: int
    content_type: str


@router.post("/jobs/{job_id}/finalize-upload")
def finalize_upload(
    job_id: str,
    payload: FinalizeUploadRequest,
    request: Request,
):
    _require_token(request, job_id)

    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    fs_update_job(
        job_id,
        {
            "file_path": payload.file_path,
            "size_bytes": payload.size_bytes,
            "content_type": payload.content_type,
            "status": JobStatus.QUEUED,
            "updated_at": _utcnow_iso(),
        },
    )

    record_event(job_id, "uploaded", "Cloud upload completed", JobStatus.QUEUED)

    dispatch_job(job_id)

    return {"message": "Upload finalized and job queued"}


# -------------------------------------------------
# 5️⃣ Status + Events
# -------------------------------------------------

@router.get("/jobs/{job_id}")
def get_job_route(job_id: str, request: Request):
    _require_token(request, job_id)

    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    return job


@router.get("/jobs/{job_id}/events")
def get_job_events_route(job_id: str, request: Request):
    _require_token(request, job_id)
    return get_events(job_id)


# -------------------------------------------------
# 6️⃣ Download Redirects
# -------------------------------------------------

@router.get("/jobs/{job_id}/docx")
def download_docx_route(job_id: str, request: Request):
    _require_token(request, job_id)
    url = get_storage().get_download_url(job_id, "transcript.docx")
    return RedirectResponse(url, status_code=302)


@router.get("/jobs/{job_id}/txt")
def download_txt_route(job_id: str, request: Request):
    _require_token(request, job_id)
    url = get_storage().get_download_url(job_id, "transcript.txt")
    return RedirectResponse(url, status_code=302)


@router.get("/jobs/{job_id}/srt")
def download_srt_route(job_id: str, request: Request):
    _require_token(request, job_id)
    url = get_storage().get_download_url(job_id, "transcript.srt")
    return RedirectResponse(url, status_code=302)


@router.get("/jobs/{job_id}/vtt")
def download_vtt_route(job_id: str, request: Request):
    _require_token(request, job_id)
    url = get_storage().get_download_url(job_id, "transcript.vtt")
    return RedirectResponse(url, status_code=302)

@router.get("/jobs/{job_id}/html")
def download_html_route(job_id: str, request: Request):
    _require_token(request, job_id)
    url = get_storage().get_download_url(job_id, "transcript.html")
    return RedirectResponse(url, status_code=302)
