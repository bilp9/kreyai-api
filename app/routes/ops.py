from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth.auth import get_current_user
from app.constants import JobStatus
from app.models.user import User
from app.services.access_control import resolve_submission_access, serialize_access_decision
from app.services.credits import adjust_credit_minutes, ensure_starter_credit_grant, get_credit_account, list_credit_ledger
from app.services.partner_plans import (
    get_partner_plan_status,
    grant_partner_plan,
    renew_partner_plan,
    revoke_partner_plan,
)
from app.state.firestore_jobs import count_jobs_by_field, count_jobs_by_status, list_recent_jobs

router = APIRouter(prefix="/ops", tags=["ops"])


class PartnerPlanRequest(BaseModel):
    email: str
    notes: Optional[str] = None


class BillingAdjustmentRequest(BaseModel):
    email: str
    action: str
    minutes: int
    notes: Optional[str] = None


def _normalize_email(email: str) -> str:
    normalized = str(email or "").strip().lower()
    if not normalized or "@" not in normalized:
        raise HTTPException(status_code=400, detail="A valid email is required.")
    return normalized


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


@router.get("/dashboard")
def get_ops_dashboard(
    limit: int = Query(25, ge=1, le=100),
    status: str | None = Query(None),
    language: str | None = Query(None),
    email: str | None = Query(None),
    user: User = Depends(get_current_user),
):
    jobs = list_recent_jobs(
        limit=limit,
        status=status,
        language=language,
        email_query=email,
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
                "audio_duration_seconds": _coerce_float(job.get("audio_duration_seconds")),
                "processing_time_seconds": _coerce_float(job.get("processing_time_seconds")),
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
            }
            for job in jobs
        ],
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
