from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.credits import is_valid_billing_email, normalize_billing_email
from app.services.dekk_licenses import (
    create_dekk_checkout_session,
    dekk_checkout_is_configured,
    dekk_private_key_is_configured,
    dekk_webhook_is_configured,
    get_dekk_plan,
    list_dekk_plans,
    record_dekk_download_event,
)

router = APIRouter(prefix="/api/dekk", tags=["dekk"])


class CreateDekkCheckoutSessionRequest(BaseModel):
    email: str
    plan: str


class DekkDownloadEventRequest(BaseModel):
    product: str | None = None
    version: str | None = None
    platform: str | None = None
    source: str | None = None
    ip_hash: str | None = None
    user_agent_hash: str | None = None
    referer: str | None = None


@router.get("/config")
def get_dekk_config():
    return {
        "checkout_enabled": dekk_checkout_is_configured(),
        "license_signing_enabled": dekk_private_key_is_configured(),
        "webhook_enabled": dekk_webhook_is_configured(),
        "plans": list_dekk_plans(),
    }


@router.post("/checkout-session")
def create_dekk_checkout_session_route(payload: CreateDekkCheckoutSessionRequest):
    normalized = normalize_billing_email(payload.email)
    if not is_valid_billing_email(normalized):
        raise HTTPException(status_code=400, detail="A valid email is required.")
    if not dekk_checkout_is_configured():
        raise HTTPException(status_code=503, detail="Dekk checkout is not configured.")

    try:
        get_dekk_plan(payload.plan)
        session = create_dekk_checkout_session(email=normalized, plan_id=payload.plan)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return session


@router.post("/download-event")
def record_dekk_download_event_route(payload: DekkDownloadEventRequest):
    try:
        return record_dekk_download_event(
            product=payload.product,
            version=payload.version,
            platform=payload.platform,
            source=payload.source,
            ip_hash=payload.ip_hash,
            user_agent_hash=payload.user_agent_hash,
            referer=payload.referer,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
