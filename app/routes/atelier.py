from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.atelier_licenses import (
    activate_atelier_license,
    atelier_checkout_is_configured,
    atelier_private_key_is_configured,
    atelier_webhook_is_configured,
    create_atelier_checkout_session,
    deactivate_atelier_license,
    list_atelier_plans,
)
from app.services.credits import is_valid_billing_email, normalize_billing_email

router = APIRouter(prefix="/api/atelier", tags=["atelier"])


class CreateAtelierCheckoutSessionRequest(BaseModel):
    email: str


class AtelierLicenseActionRequest(BaseModel):
    license_key: str
    machine_id: str


@router.get("/config")
def get_atelier_config():
    return {
        "checkout_enabled": atelier_checkout_is_configured(),
        "license_signing_enabled": atelier_private_key_is_configured(),
        "webhook_enabled": atelier_webhook_is_configured(),
        "plans": list_atelier_plans(),
    }


@router.post("/checkout-session")
def create_atelier_checkout_session_route(payload: CreateAtelierCheckoutSessionRequest):
    normalized = normalize_billing_email(payload.email)
    if not is_valid_billing_email(normalized):
        raise HTTPException(status_code=400, detail="A valid email is required.")
    if not atelier_checkout_is_configured():
        raise HTTPException(status_code=503, detail="aTelier checkout is not configured.")

    try:
        session = create_atelier_checkout_session(email=normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return session


@router.post("/activate")
def activate_atelier_license_route(payload: AtelierLicenseActionRequest):
    # Always 200 with {"valid": bool, "error": ...} — the desktop client distinguishes
    # "malformed request" (raised below) from "this key/machine combo isn't valid" (business
    # logic, still a normal response) so it can show the server's message verbatim.
    return activate_atelier_license(license_key=payload.license_key, machine_id=payload.machine_id)


@router.post("/deactivate")
def deactivate_atelier_license_route(payload: AtelierLicenseActionRequest):
    return deactivate_atelier_license(license_key=payload.license_key, machine_id=payload.machine_id)
