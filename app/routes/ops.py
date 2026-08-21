from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import asdict
import hashlib
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.auth import get_current_user
from app.constants import JobStatus
from app.models.user import User
from app.services.access_control import resolve_submission_access, serialize_access_decision
from app.services.credits import adjust_credit_minutes, ensure_starter_credit_grant, get_credit_account, list_credit_ledger
from app.services.atelier_licenses import issue_atelier_partner_license
from app.services.dekk_licenses import issue_dekk_partner_license
from app.services.docx_export import build_docx_bytes
from app.services.email_service import send_linguist_partner_license_email
from app.services.partner_plans import (
    get_partner_plan_status,
    grant_partner_plan,
    renew_partner_plan,
    revoke_partner_plan,
)
from app.storage.backend import get_storage
from app.state.firestore_jobs import count_jobs_by_field, count_jobs_by_status, list_recent_jobs
from app.state.firestore_jobs import get_job as fs_get_job, update_job as fs_update_job
from app.services.ht_llm_review import DEFAULT_PROMPT
from app.services.ht_review_jobs import run_ht_review_job, start_ht_review_job

router = APIRouter(prefix="/ops", tags=["ops"])


class PartnerPlanRequest(BaseModel):
    email: str
    notes: Optional[str] = None


class LinguistPartnerLicenseRequest(BaseModel):
    email: str
    name: Optional[str] = None
    cohort: str = "2026"
    products: List[str] = Field(default_factory=lambda: ["atelier", "dekk"])


class BillingAdjustmentRequest(BaseModel):
    email: str
    action: str
    minutes: int
    notes: Optional[str] = None


class HTReviewRunRequest(BaseModel):
    model: Optional[str] = None
    prompt: Optional[str] = None
    glossary_terms: List[str] = Field(default_factory=list)


class HTReviewApproveRequest(BaseModel):
    approved_text: str


def _normalize_email(email: str) -> str:
    normalized = str(email or "").strip().lower()
    if not normalized or "@" not in normalized:
        raise HTTPException(status_code=400, detail="A valid email is required.")
    return normalized


def _linguist_partner_id(*, email: str, cohort: str) -> str:
    value = f"{cohort.strip().lower()}:{email.strip().lower()}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:20]


@router.post("/licenses/linguist-partner")
async def issue_linguist_partner_license_route(
    payload: LinguistPartnerLicenseRequest,
    user: User = Depends(get_current_user),
):
    email = _normalize_email(payload.email)
    cohort = str(payload.cohort or "2026").strip() or "2026"
    products = list(dict.fromkeys(str(item or "").strip().lower() for item in payload.products))
    if not products or any(product not in {"atelier", "dekk"} for product in products):
        raise HTTPException(status_code=400, detail="Products must include aTelier, Dekk, or both.")

    participant_id = _linguist_partner_id(email=email, cohort=cohort)
    issued_by = user.email or user.id
    results: dict[str, dict[str, Any]] = {}
    licenses_to_email: dict[str, str] = {}

    try:
        if "atelier" in products:
            result = issue_atelier_partner_license(
                participant_id=participant_id,
                email=email,
                participant_name=payload.name,
                cohort=cohort,
                issued_by=issued_by,
            )
            results["atelier"] = result
            if result.get("applied"):
                licenses_to_email["atelier"] = str(result.get("license_key") or "")

        if "dekk" in products:
            result = issue_dekk_partner_license(
                participant_id=participant_id,
                email=email,
                participant_name=payload.name,
                cohort=cohort,
                issued_by=issued_by,
            )
            results["dekk"] = result
            if result.get("applied"):
                licenses_to_email["dekk"] = str(result.get("license_key") or "")
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if licenses_to_email:
        await send_linguist_partner_license_email(
            email=email,
            participant_name=payload.name,
            licenses=licenses_to_email,
        )

    return {
        "participant_id": participant_id,
        "email": email,
        "cohort": cohort,
        "products": {
            product: {
                "license_id": str(result.get("license_id") or ""),
                "issued": bool(result.get("applied")),
            }
            for product, result in results.items()
        },
        "email_sent": bool(licenses_to_email),
        "issued_by": issued_by,
    }


def _average(values: List[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _utcnow_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")


def _parse_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _date_start_iso(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return datetime(
        parsed.year,
        parsed.month,
        parsed.day,
        0,
        0,
        0,
        tzinfo=timezone.utc,
    ).isoformat()


def _date_end_iso(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return datetime(
        parsed.year,
        parsed.month,
        parsed.day,
        23,
        59,
        59,
        999999,
        tzinfo=timezone.utc,
    ).isoformat()


def _storage_exists_for_job(job_id: str) -> bool:
    storage = get_storage()
    return storage.prefix_exists(f"jobs/{job_id}/uploads/") or storage.prefix_exists(f"jobs/{job_id}/outputs/")


def _read_optional_output_text(job_id: str, filename: str) -> str | None:
    storage = get_storage()
    if not storage.output_exists(job_id, filename):
        return None
    return storage.read_output_text(job_id, filename)


def _serialize_retention(job: Dict[str, Any]) -> Dict[str, Any]:
    completed_at = _parse_datetime(job.get("completed_at"))
    files_deleted_at = str(job.get("files_deleted_at") or "").strip() or None
    auto_deleted_at = str(job.get("auto_deleted_at") or "").strip() or None
    deleted_blob_count = int(job.get("deleted_blob_count") or 0)
    scheduled_delete_at = (
        (completed_at + timedelta(days=7)).isoformat() if completed_at is not None else None
    )
    scheduled_delete_dt = _parse_datetime(scheduled_delete_at)
    last_storage_check_at = datetime.now(timezone.utc).isoformat()
    storage_objects_present = _storage_exists_for_job(str(job.get("job_id") or ""))
    now = datetime.now(timezone.utc)

    if files_deleted_at:
        storage_status = "customer_deleted"
        retention_source = "customer_request"
    elif auto_deleted_at:
        storage_status = "expired_deleted"
        retention_source = "lifecycle_rule"
    elif storage_objects_present:
        storage_status = "available"
        retention_source = "active"
    elif scheduled_delete_dt and scheduled_delete_dt <= now:
        storage_status = "expired_deleted"
        retention_source = "lifecycle_rule_inferred"
    elif completed_at is not None:
        storage_status = "missing"
        retention_source = "unknown"
    else:
        storage_status = "not_ready"
        retention_source = "active"

    return {
        "scheduled_delete_at": scheduled_delete_at,
        "auto_deleted_at": auto_deleted_at,
        "files_deleted_at": files_deleted_at,
        "deleted_blob_count": deleted_blob_count,
        "storage_status": storage_status,
        "storage_objects_present": storage_objects_present,
        "last_storage_check_at": last_storage_check_at,
        "retention_source": retention_source,
    }


@router.get("/dashboard")
def get_ops_dashboard(
    limit: int = Query(25, ge=1, le=100),
    status: str | None = Query(None),
    language: str | None = Query(None),
    email: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    user: User = Depends(get_current_user),
):
    created_from = _date_start_iso(date_from)
    created_to = _date_end_iso(date_to)
    jobs = list_recent_jobs(
        limit=limit,
        status=status,
        language=language,
        email_query=email,
        created_from=created_from,
        created_to=created_to,
    )

    completed_jobs = [
        job for job in jobs if str(job.get("status") or "").lower() == JobStatus.COMPLETED.value
    ]
    failed_jobs = [
        job for job in jobs if str(job.get("status") or "").lower() == JobStatus.FAILED.value
    ]

    processing_times = [
        value
        for job in completed_jobs
        if (value := _coerce_float(job.get("processing_time_seconds"))) is not None
    ]
    realtime_factors = [
        value
        for job in completed_jobs
        if (value := _coerce_float(job.get("realtime_factor"))) is not None
    ]
    estimated_costs = [
        value
        for job in jobs
        if (value := _coerce_float(job.get("estimated_cost_usd"))) is not None
    ]
    audio_seconds = [
        value
        for job in jobs
        if (value := _coerce_float(job.get("audio_duration_seconds"))) is not None
    ]

    status_counts = {
        status.value: count_jobs_by_status(status.value)
        for status in JobStatus
    }
    lane_counts = {
        "cpu": count_jobs_by_field("execution_lane", "cpu"),
        "gpu": count_jobs_by_field("execution_lane", "gpu"),
    }
    tier_counts = {
        "standard": count_jobs_by_field("processing_tier", "standard"),
        "premium": count_jobs_by_field("processing_tier", "premium"),
    }

    return {
        "viewer": {
            "id": user.id,
            "name": user.name,
            "plan": user.plan,
            "email": user.email,
        },
        "filters": {
            "limit": limit,
            "status": status,
            "language": language,
            "email": email,
            "date_from": date_from,
            "date_to": date_to,
        },
        "summary": {
            "recent_jobs_count": len(jobs),
            "recent_completed_jobs": len(completed_jobs),
            "recent_failed_jobs": len(failed_jobs),
            "recent_audio_minutes": round(sum(audio_seconds) / 60, 2),
            "recent_estimated_cost_usd": round(sum(estimated_costs), 4),
            "avg_processing_time_seconds": _average(processing_times),
            "avg_realtime_factor": _average(realtime_factors),
            "status_counts": status_counts,
            "lane_counts": lane_counts,
            "tier_counts": tier_counts,
        },
        "jobs": [
            {
                "job_id": job.get("job_id"),
                "email": job.get("email"),
                "status": job.get("status"),
                "progress": int(job.get("progress") or 0),
                "status_message": job.get("status_message"),
                "language": job.get("language"),
                "language_requested": job.get("language_requested"),
                "language_final": job.get("language_final"),
                "language_detected": job.get("language_detected"),
                "created_at": job.get("created_at"),
                "updated_at": job.get("updated_at"),
                "completed_at": job.get("completed_at"),
                **_serialize_retention(job),
                "audio_duration_seconds": _coerce_float(job.get("audio_duration_seconds")),
                "processing_time_seconds": _coerce_float(job.get("processing_time_seconds")),
                "download_time_seconds": _coerce_float(job.get("download_time_seconds")),
                "diarization_time_seconds": _coerce_float(job.get("diarization_time_seconds")),
                "transcription_time_seconds": _coerce_float(job.get("transcription_time_seconds")),
                "alignment_time_seconds": _coerce_float(job.get("alignment_time_seconds")),
                "output_time_seconds": _coerce_float(job.get("output_time_seconds")),
                "estimated_cost_usd": _coerce_float(job.get("estimated_cost_usd")),
                "realtime_factor": _coerce_float(job.get("realtime_factor")),
                "attempts": int(job.get("attempts") or 0),
                "speaker_mode": job.get("speaker_mode"),
                "processing_tier": job.get("processing_tier"),
                "execution_lane": job.get("execution_lane"),
                "requires_diarization": job.get("requires_diarization"),
                "worker_job_name": job.get("worker_job_name"),
                "worker_job_region": job.get("worker_job_region"),
                "routing_reason": job.get("routing_reason"),
                "dispatch_error": job.get("dispatch_error"),
                "diarization_status": job.get("diarization_status"),
                "diarization_error": job.get("diarization_error"),
                "diarization_segments_count": int(job.get("diarization_segments_count") or 0),
                "speaker_labeled_segments_count": int(job.get("speaker_labeled_segments_count") or 0),
                "content_type": job.get("content_type"),
                "file_size_bytes": _coerce_float(job.get("file_size_bytes") or job.get("size_bytes")),
                "ht_review_updated_at": job.get("ht_review_updated_at"),
                "ht_review_model": job.get("ht_review_model"),
                "ht_review_approved_at": job.get("ht_review_approved_at"),
            }
            for job in jobs
        ],
    }


@router.get("/jobs/{job_id}/ht-review")
def get_ht_review_route(
    job_id: str,
    user: User = Depends(get_current_user),
):
    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    raw_text = _read_optional_output_text(job_id, "transcript.txt")
    corrected_text = _read_optional_output_text(job_id, "transcript.llm-corrected.txt")
    approved_text = _read_optional_output_text(job_id, "transcript.approved.txt")
    review_meta_raw = _read_optional_output_text(job_id, "transcript.llm-review.json")

    review_meta = None
    if review_meta_raw:
        try:
            review_meta = __import__("json").loads(review_meta_raw)
        except Exception:
            review_meta = None

    return {
        "viewer": {
            "id": user.id,
            "email": user.email,
        },
        "job_id": job_id,
        "language": job.get("language_final") or job.get("language") or job.get("language_requested"),
        "status": job.get("status"),
        "raw_text": raw_text,
        "corrected_text": corrected_text,
        "approved_text": approved_text,
        "review_meta": review_meta,
        "default_prompt": DEFAULT_PROMPT,
        "ht_review_status": job.get("ht_review_status"),
        "ht_review_error": job.get("ht_review_error"),
        "ht_review_requested_at": job.get("ht_review_requested_at"),
        "ht_review_glossary_terms": job.get("ht_review_glossary_terms") or [],
    }


@router.post("/jobs/{job_id}/ht-review/run")
def run_ht_review_route(
    job_id: str,
    payload: HTReviewRunRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    language = str(job.get("language_final") or job.get("language") or "").strip().lower()
    if language != "ht":
        raise HTTPException(status_code=400, detail="LLM review is currently enabled for Haitian Creole jobs only.")

    storage = get_storage()
    if not storage.output_exists(job_id, "transcript.txt"):
        raise HTTPException(status_code=404, detail="Raw transcript output is not available yet.")

    start_result = start_ht_review_job(
        job_id,
        model=payload.model,
        prompt=payload.prompt,
        glossary_terms=payload.glossary_terms,
    )
    if start_result.get("queued"):
        background_tasks.add_task(
            run_ht_review_job,
            job_id,
            model=payload.model,
            prompt=payload.prompt,
            glossary_terms=payload.glossary_terms,
        )

    return {
        "job_id": job_id,
        "accepted": True,
        "queued": bool(start_result.get("queued")),
        "already_running": bool(start_result.get("already_running")),
        "status": "running",
        "message": (
            "HT review is already running."
            if start_result.get("already_running")
            else "HT review started."
        ),
    }


@router.post("/jobs/{job_id}/ht-review/approve")
def approve_ht_review_route(
    job_id: str,
    payload: HTReviewApproveRequest,
    user: User = Depends(get_current_user),
):
    job = fs_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    approved_text = str(payload.approved_text or "").strip()
    if not approved_text:
        raise HTTPException(status_code=400, detail="approved_text is required.")

    storage = get_storage()
    storage.save_output(
        job_id,
        "transcript.approved.txt",
        (approved_text + "\n").encode("utf-8"),
        "text/plain; charset=utf-8",
    )
    storage.save_output(
        job_id,
        "transcript.approved.docx",
        build_docx_bytes(approved_text),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    fs_update_job(
        job_id,
        {
            "ht_review_approved_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    return {
        "job_id": job_id,
        "approved": True,
    }


@router.get("/partner")
def get_partner_plan_route(
    email: str = Query(...),
    user: User = Depends(get_current_user),
):
    normalized_email = _normalize_email(email)
    return {
        "viewer": {
            "id": user.id,
            "email": user.email,
        },
        "partner_access": get_partner_plan_status(normalized_email),
    }


@router.get("/access")
def get_access_decision_route(
    email: str = Query(...),
    user: User = Depends(get_current_user),
):
    normalized_email = _normalize_email(email)
    decision = resolve_submission_access(normalized_email)
    return {
        "viewer": {
            "id": user.id,
            "email": user.email,
        },
        "email": normalized_email,
        "access_decision": serialize_access_decision(decision),
        "partner_access": get_partner_plan_status(normalized_email),
    }


@router.get("/billing")
def get_ops_billing_route(
    email: str = Query(...),
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
):
    normalized_email = _normalize_email(email)
    ensure_starter_credit_grant(normalized_email)
    account = get_credit_account(normalized_email)
    ledger = list_credit_ledger(normalized_email, limit=limit)
    decision = resolve_submission_access(normalized_email)

    return {
        "viewer": {
            "id": user.id,
            "email": user.email,
        },
        "email": normalized_email,
        "account": asdict(account),
        "access_decision": serialize_access_decision(decision),
        "partner_access": get_partner_plan_status(normalized_email),
        "ledger": [asdict(entry) for entry in ledger],
    }


@router.post("/billing/adjust")
def adjust_billing_credits_route(
    payload: BillingAdjustmentRequest,
    user: User = Depends(get_current_user),
):
    normalized_email = _normalize_email(payload.email)
    action = str(payload.action or "").strip().lower()
    if action not in {"grant", "refund", "debit"}:
        raise HTTPException(status_code=400, detail="Adjustment action must be grant, refund, or debit.")
    minutes = int(payload.minutes or 0)
    if minutes <= 0:
        raise HTTPException(status_code=400, detail="Minutes must be greater than zero.")

    try:
        result = adjust_credit_minutes(
            email=normalized_email,
            minutes=minutes,
            action=action,
            idempotency_key=f"ops:{action}:{normalized_email}:{_utcnow_compact()}",
            source="ops_manual_adjustment",
            description=(payload.notes or f"Manual {action} by ops").strip(),
            metadata={
                "approved_by": user.email or user.id,
                "notes": (payload.notes or "").strip(),
                "action": action,
            },
        )
    except ValueError as exc:
        detail = str(exc)
        status = 400 if detail != "insufficient_credits" else 409
        raise HTTPException(status_code=status, detail=detail) from exc

    account = get_credit_account(normalized_email)
    return {
        "viewer": {
            "id": user.id,
            "email": user.email,
        },
        "email": normalized_email,
        "action": action,
        "minutes": minutes,
        "result": result,
        "account": asdict(account),
    }


@router.post("/partner/grant")
def grant_partner_plan_route(
    payload: PartnerPlanRequest,
    user: User = Depends(get_current_user),
):
    normalized_email = _normalize_email(payload.email)
    plan = grant_partner_plan(
        normalized_email,
        approved_by=user.email or user.id,
        notes=payload.notes,
    )
    return {
        "email": normalized_email,
        "action": "granted",
        "plan": asdict(plan),
    }


@router.post("/partner/renew")
def renew_partner_plan_route(
    payload: PartnerPlanRequest,
    user: User = Depends(get_current_user),
):
    normalized_email = _normalize_email(payload.email)
    plan = renew_partner_plan(
        normalized_email,
        approved_by=user.email or user.id,
        notes=payload.notes,
    )
    return {
        "email": normalized_email,
        "action": "renewed",
        "plan": asdict(plan),
    }


@router.post("/partner/revoke")
def revoke_partner_plan_route(
    payload: PartnerPlanRequest,
    user: User = Depends(get_current_user),
):
    normalized_email = _normalize_email(payload.email)
    result = revoke_partner_plan(normalized_email)
    return {
        "viewer": {
            "id": user.id,
            "email": user.email,
        },
        "email": normalized_email,
        "action": "revoked",
        **result,
    }
