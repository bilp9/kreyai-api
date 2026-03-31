# app/routes/jobs.py

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.config import get_language_label, get_public_api_version, get_public_language_options, get_public_supported_language_codes
from app.constants import JobStatus, JOB_ID_PREFIX, SpeakerMode
from app.constants import (
    PUBLIC_CREATE_JOB_RATE_LIMIT,
    PUBLIC_RATE_LIMIT_WINDOW_SECONDS,
    VERIFICATION_CODE_TTL_MINUTES,
    PUBLIC_VERIFY_RATE_LIMIT,
    VERIFICATION_LOCKOUT_SECONDS,
    VERIFICATION_MAX_ATTEMPTS,
)
from app.state.firestore_jobs import (
    create_job as fs_create_job,
    get_job as fs_get_job,
    update_job as fs_update_job,
)
from app.processing.dispatcher import dispatch_job
from app.processing.routing import resolve_processing_route
from app.processing.runner import get_audio_duration_seconds
from app.events.recorder import record_event, get_events
from app.storage.backend import get_storage
from app.services.access_control import resolve_submission_access, serialize_access_decision
from app.services.credits import consume_credit_minutes, refund_credit_minutes
from app.services.email_service import send_files_deleted_email, send_internal_new_order_email, send_verification_email
from app.transcription.engine import normalize_language_code
from app.security.job_tokens import (
    JobTokenConfig,
    mint_job_token,
    verify_job_token,
    TokenExpired,
    TokenInvalid,
)

router = APIRouter(prefix="/api", tags=["jobs"])
_PUBLIC_RATE_LIMITS: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utcnow_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _verification_expiry_iso() -> str:
    return (
        datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_CODE_TTL_MINUTES)
    ).isoformat()


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client and request.client.host:
        return str(request.client.host)
    return "unknown"


def _enforce_public_rate_limit(request: Request, *, scope: str, limit: int) -> None:
    now = time.monotonic()
    key = (scope, _client_ip(request))
    hits = _PUBLIC_RATE_LIMITS[key]
    window_seconds = PUBLIC_RATE_LIMIT_WINDOW_SECONDS

    while hits and now - hits[0] >= window_seconds:
        hits.popleft()

    if len(hits) >= limit:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait a moment and try again.",
        )

    hits.append(now)


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


def _normalize_email(email: str) -> str:
    normalized = str(email or "").strip().lower()
    if not normalized or not _EMAIL_PATTERN.match(normalized):
        raise HTTPException(
            status_code=400,
            detail="Please enter a valid email address.",
        )
    return normalized


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


def _validate_upload_path(job_id: str, file_path: str) -> str:
    normalized_path = str(file_path or "").strip()
    expected_prefix = f"jobs/{job_id}/uploads/"

    if not normalized_path.startswith(expected_prefix):
        raise HTTPException(
            status_code=400,
            detail="Upload path does not belong to this job.",
        )

    storage = get_storage()
    if not storage.blob_exists(normalized_path):
        raise HTTPException(
            status_code=400,
            detail="Uploaded file could not be found. Please upload again.",
        )

    return normalized_path


def _probe_uploaded_audio_duration_seconds(file_path: str) -> float:
    storage = get_storage()
    suffix = os.path.splitext(file_path)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        local_path = tmp.name

    try:
        storage.download_to_file(file_path, local_path)
        return float(get_audio_duration_seconds(local_path))
    finally:
        try:
            os.unlink(local_path)
        except OSError:
            pass


def _job_files_deleted(job: dict) -> bool:
    return bool(job.get("files_deleted_at"))


# -------------------------------------------------
# 1️⃣ Create Job
# -------------------------------------------------

@router.post("/")
async def create_job_route(
    request: Request,
    background_tasks: BackgroundTasks,
    response: Response,
    email: str = Body(...),
    language: str = Body("auto"),
    accepted_terms: bool = Body(False),
):
    _enforce_public_rate_limit(
        request,
        scope="create_job",
        limit=PUBLIC_CREATE_JOB_RATE_LIMIT,
    )
    started_at = time.perf_counter()
    email = _normalize_email(email)
    language = _normalize_requested_language(language)
    access_decision = resolve_submission_access(email)

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
        "verification_expires_at": _verification_expiry_iso(),
        "verified": False,
        "status": JobStatus.PENDING_VERIFICATION,
        "created_at": _utcnow_iso(),
        "updated_at": _utcnow_iso(),
        "progress": 0,
        "access_decision": serialize_access_decision(access_decision),
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
def verify_job_route(job_id: str, code: str, request: Request):
    _enforce_public_rate_limit(
        request,
        scope="verify_job",
        limit=PUBLIC_VERIFY_RATE_LIMIT,
    )
    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if _job_files_deleted(job):
        raise HTTPException(status_code=410, detail="Files for this job were deleted at the customer's request.")

    if job.get("verified"):
        raise HTTPException(400, "Job already verified")

    now_ts = _utcnow_ts()
    verification_expires_at = job.get("verification_expires_at")
    if verification_expires_at:
        try:
            expires_ts = datetime.fromisoformat(str(verification_expires_at)).timestamp()
        except ValueError:
            expires_ts = 0.0
        if expires_ts <= now_ts:
            fs_update_job(
                job_id,
                {
                    "status": JobStatus.EXPIRED,
                    "status_message": "Verification code expired",
                    "updated_at": _utcnow_iso(),
                },
            )
            raise HTTPException(
                status_code=410,
                detail="Verification code expired. Please start again.",
            )

    locked_until = float(job.get("verification_locked_until") or 0.0)
    if locked_until > now_ts:
        raise HTTPException(
            status_code=429,
            detail="Too many verification attempts. Please try again later.",
        )

    if code != job.get("verification_code"):
        attempts = int(job.get("verification_attempts") or 0) + 1
        updates = {
            "verification_attempts": attempts,
            "updated_at": _utcnow_iso(),
        }
        if attempts >= VERIFICATION_MAX_ATTEMPTS:
            updates["verification_locked_until"] = now_ts + VERIFICATION_LOCKOUT_SECONDS
        fs_update_job(job_id, updates)
        raise HTTPException(400, "Invalid verification code")

    fs_update_job(
        job_id,
        {
            "verified": True,
            "status": JobStatus.VERIFIED,
            "verification_attempts": 0,
            "verification_locked_until": None,
            "verification_code": None,
            "verified_at": _utcnow_iso(),
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
    speaker_mode: str = SpeakerMode.UNSURE.value


@router.post("/jobs/{job_id}/finalize-upload")
def finalize_upload(
    job_id: str,
    payload: FinalizeUploadRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    _require_token(request, job_id)

    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    file_path = _validate_upload_path(job_id, payload.file_path)
    try:
        audio_duration_seconds = _probe_uploaded_audio_duration_seconds(file_path)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Unable to inspect uploaded media duration: {exc}",
        ) from exc

    access_decision = resolve_submission_access(
        str(job.get("email") or ""),
        audio_duration_seconds=audio_duration_seconds,
    )
    route = resolve_processing_route(payload.speaker_mode)

    if not access_decision.allowed:
        fs_update_job(
            job_id,
            {
                "status": JobStatus.VERIFIED,
                "status_message": "Credits are required before this job can be processed.",
                "access_decision": serialize_access_decision(access_decision),
                "audio_duration_seconds": audio_duration_seconds,
                "updated_at": _utcnow_iso(),
            },
        )
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Insufficient credits for this upload.",
                "required_minutes": access_decision.credits_to_deduct,
                "available_minutes": access_decision.available_credits,
                "missing_minutes": access_decision.missing_credits,
                "audio_duration_seconds": audio_duration_seconds,
            },
        )

    credits_charged_minutes = 0
    if (
        access_decision.requires_credit_check
        and access_decision.source == "credits"
        and access_decision.reason == "credits_ok"
        and access_decision.credits_to_deduct > 0
    ):
        try:
            consume_credit_minutes(
                email=str(job.get("email") or ""),
                minutes=int(access_decision.credits_to_deduct),
                idempotency_key=f"job_debit:{job_id}",
                source="job_finalize_upload",
                description=f"Reserved credits for job {job_id}",
                metadata={
                    "job_id": job_id,
                    "speaker_mode": payload.speaker_mode,
                    "processing_tier": route.get("processing_tier"),
                },
            )
            credits_charged_minutes = int(access_decision.credits_to_deduct)
        except ValueError as exc:
            if str(exc) == "insufficient_credits":
                raise HTTPException(
                    status_code=402,
                    detail={
                        "message": "Insufficient credits for this upload.",
                        "required_minutes": access_decision.credits_to_deduct,
                        "available_minutes": 0,
                        "missing_minutes": access_decision.credits_to_deduct,
                        "audio_duration_seconds": audio_duration_seconds,
                    },
                ) from exc
            raise

    fs_update_job(
        job_id,
        {
            "file_path": file_path,
            "size_bytes": payload.size_bytes,
            "content_type": payload.content_type,
            "audio_duration_seconds": audio_duration_seconds,
            "credits_charged_minutes": credits_charged_minutes,
            **route,
            "status": JobStatus.QUEUED,
            "status_message": (
                "Your file has been uploaded successfully. Premium speaker labeling will begin shortly."
                if route["requires_diarization"]
                else "Your file has been uploaded successfully. Standard transcription will begin shortly."
            ),
            "access_decision": serialize_access_decision(access_decision),
            "updated_at": _utcnow_iso(),
        },
    )

    record_event(job_id, "uploaded", "Cloud upload completed", JobStatus.QUEUED)

    try:
        dispatch_job(
            job_id,
            worker_job_name=str(route["worker_job_name"]),
            worker_job_region=str(route["worker_job_region"]),
            execution_lane=str(route["execution_lane"]),
            requires_diarization=bool(route["requires_diarization"]),
        )
    except Exception as exc:
        if credits_charged_minutes > 0:
            refund_credit_minutes(
                email=str(job.get("email") or ""),
                minutes=credits_charged_minutes,
                idempotency_key=f"job_refund_dispatch:{job_id}",
                source="dispatch_failure",
                description=f"Returned credits after dispatch failure for {job_id}",
                metadata={"job_id": job_id},
            )
        fs_update_job(
            job_id,
            {
                "status": JobStatus.VERIFIED,
                "status_message": "Upload received but processing could not be started. Please retry.",
                "dispatch_error": str(exc),
                "updated_at": _utcnow_iso(),
            },
        )
        raise HTTPException(
            status_code=503,
            detail="Upload received, but processing could not be started. Please try again.",
        ) from exc

    background_tasks.add_task(
        send_internal_new_order_email,
        job_id=job_id,
        customer_email=str(job.get("email") or ""),
        language=str(job.get("language") or "auto"),
        speaker_mode=str(payload.speaker_mode),
        processing_tier=str(route.get("processing_tier") or "standard"),
        execution_lane=str(route.get("execution_lane") or "cpu"),
        worker_job_name=str(route.get("worker_job_name") or ""),
        file_path=file_path,
        size_bytes=int(payload.size_bytes),
        content_type=str(payload.content_type),
    )

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


@router.post("/jobs/{job_id}/delete-files")
def delete_job_files_route(job_id: str, request: Request, background_tasks: BackgroundTasks):
    _require_token(request, job_id)

    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if _job_files_deleted(job):
        return {
            "message": "Files were already deleted.",
            "files_deleted_at": job.get("files_deleted_at"),
            "deleted_blob_count": int(job.get("deleted_blob_count") or 0),
        }

    deleted_blob_count = get_storage().delete_job_files(job_id)
    deleted_at = _utcnow_iso()
    current_status = str(job.get("status") or "")
    next_status = "customer_deleted" if current_status.lower() == JobStatus.COMPLETED.value else current_status

    fs_update_job(
        job_id,
        {
            "status": next_status,
            "status_message": (
                "Files were deleted from active storage at your request. Download links no longer work. "
                "If you need them again, please submit a new request."
            ),
            "files_deleted_at": deleted_at,
            "deleted_blob_count": deleted_blob_count,
            "updated_at": deleted_at,
        },
    )
    record_event(job_id, "files_deleted", "Customer requested immediate file deletion", next_status)

    if job.get("email"):
        background_tasks.add_task(send_files_deleted_email, str(job.get("email")), job_id)

    return {
        "message": "Files deleted successfully.",
        "files_deleted_at": deleted_at,
        "deleted_blob_count": deleted_blob_count,
    }


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
    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if _job_files_deleted(job):
        raise HTTPException(status_code=410, detail="Files for this job were deleted at the customer's request.")
    try:
        url = get_storage().get_download_url(job_id, "transcript.docx")
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(url, status_code=302)


@router.get("/jobs/{job_id}/txt")
def download_txt_route(job_id: str, request: Request):
    _require_token(request, job_id)
    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if _job_files_deleted(job):
        raise HTTPException(status_code=410, detail="Files for this job were deleted at the customer's request.")
    try:
        url = get_storage().get_download_url(job_id, "transcript.txt")
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(url, status_code=302)


@router.get("/jobs/{job_id}/srt")
def download_srt_route(job_id: str, request: Request):
    _require_token(request, job_id)
    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if _job_files_deleted(job):
        raise HTTPException(status_code=410, detail="Files for this job were deleted at the customer's request.")
    try:
        url = get_storage().get_download_url(job_id, "transcript.srt")
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(url, status_code=302)


@router.get("/jobs/{job_id}/vtt")
def download_vtt_route(job_id: str, request: Request):
    _require_token(request, job_id)
    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if _job_files_deleted(job):
        raise HTTPException(status_code=410, detail="Files for this job were deleted at the customer's request.")
    try:
        url = get_storage().get_download_url(job_id, "transcript.vtt")
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(url, status_code=302)

@router.get("/jobs/{job_id}/html")
def download_html_route(job_id: str, request: Request):
    _require_token(request, job_id)
    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if _job_files_deleted(job):
        raise HTTPException(status_code=410, detail="Files for this job were deleted at the customer's request.")
    try:
        url = get_storage().get_download_url(job_id, "transcript.html")
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(url, status_code=302)
