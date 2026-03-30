from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.services.credits import add_credit_minutes, get_credit_account, normalize_billing_email
from app.services.stripe_billing import (
    create_checkout_session,
    get_credit_pack,
    list_credit_packs,
    stripe_is_configured,
    construct_webhook_event,
)


router = APIRouter(prefix="/api/billing", tags=["billing"])
stripe_router = APIRouter(prefix="/api/stripe", tags=["billing"])


def _object_to_mapping(value) -> dict:
    if value is None:
        return {}

    if isinstance(value, dict):
        return dict(value)

    internal = getattr(value, "_data", None)
    if isinstance(internal, dict):
        return dict(internal)

    try:
        return value.to_dict()
    except Exception:
        return {}


class CreateCheckoutSessionRequest(BaseModel):
    email: str
    pack_id: str
    job_id: str | None = None
    job_token: str | None = None


@router.get("/config")
def get_billing_config():
    return {
        "stripe_enabled": stripe_is_configured(),
        "packs": list_credit_packs(),
    }


@router.get("/balance")
def get_balance(email: str = Query(...)):
    normalized = normalize_billing_email(email)
    if not normalized:
        raise HTTPException(status_code=400, detail="Email is required.")

    account = get_credit_account(normalized)
    return {
        "email": account.email,
        "balance_minutes": account.balance_minutes,
        "total_purchased_minutes": account.total_purchased_minutes,
        "total_consumed_minutes": account.total_consumed_minutes,
        "total_refunded_minutes": account.total_refunded_minutes,
        "stripe_customer_id": account.stripe_customer_id,
    }


@router.post("/checkout-session")
def create_checkout_session_route(payload: CreateCheckoutSessionRequest):
    normalized = normalize_billing_email(payload.email)
    if not normalized:
        raise HTTPException(status_code=400, detail="Email is required.")
    if not stripe_is_configured():
        raise HTTPException(status_code=503, detail="Stripe billing is not configured.")

    try:
        get_credit_pack(payload.pack_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session = create_checkout_session(
        email=normalized,
        pack_id=payload.pack_id,
        job_id=payload.job_id,
        job_token=payload.job_token,
    )
    return session


@stripe_router.post("/webhook")
async def stripe_webhook_route(request: Request):
    signature = request.headers.get("Stripe-Signature", "")
    payload = await request.body()

    try:
        event = construct_webhook_event(payload, signature)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Stripe webhook: {exc}") from exc

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = _object_to_mapping(getattr(session, "metadata", None))
        customer_details = _object_to_mapping(getattr(session, "customer_details", None))
        payment_status = str(getattr(session, "payment_status", "") or "")
        if payment_status == "paid":
            customer_email = str(customer_details.get("email") or "")
            email = normalize_billing_email(metadata.get("email") or customer_email)
            pack_id = str(metadata.get("pack_id") or "").strip().lower()
            credits_minutes = int(metadata.get("credits_minutes") or 0)
            session_id = str(getattr(session, "id", "") or "")
            if email and pack_id and credits_minutes > 0 and session_id:
                add_credit_minutes(
                    email=email,
                    minutes=credits_minutes,
                    source="stripe_checkout",
                    description=f"Stripe checkout purchase for {pack_id}",
                    idempotency_key=f"stripe_checkout:{session_id}",
                    metadata={
                        "stripe_session_id": session_id,
                        "pack_id": pack_id,
                        "amount_total": getattr(session, "amount_total", None),
                    },
                    stripe_customer_id=getattr(session, "customer", None),
                )

    return {"received": True}
