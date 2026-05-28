from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional
from urllib.parse import urlencode

import stripe

from app.services.credits import normalize_billing_email


@dataclass(frozen=True)
class CreditPack:
    id: str
    name: str
    price_cents: int
    credits_minutes: int
    label: str
    description: str


CREDIT_PACKS: Dict[str, CreditPack] = {
    "starter": CreditPack(
        id="starter",
        name="Starter Pack",
        price_cents=1000,
        credits_minutes=120,
        label="Popular",
        description="A straightforward pack for regular transcription work.",
    ),
    "growth": CreditPack(
        id="growth",
        name="Growth Pack",
        price_cents=2500,
        credits_minutes=330,
        label="Best value",
        description="Lower effective cost per minute for heavier workflows.",
    ),
}


def list_credit_packs() -> List[Dict[str, object]]:
    return [
        {
            **asdict(pack),
            "price_usd": f"{pack.price_cents / 100:.2f}",
        }
        for pack in CREDIT_PACKS.values()
    ]


def get_credit_pack(pack_id: str) -> CreditPack:
    normalized = str(pack_id or "").strip().lower()
    pack = CREDIT_PACKS.get(normalized)
    if not pack:
        raise ValueError("Unknown credit pack")
    return pack


def _frontend_base_url() -> str:
    return os.getenv("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")


def stripe_is_configured() -> bool:
    return bool(os.getenv("STRIPE_SECRET_KEY") and os.getenv("STRIPE_WEBHOOK_SECRET"))


def _api_key() -> str:
    value = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not value:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    return value


def _webhook_secret() -> str:
    value = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    if not value:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is not configured")
    return value


def create_checkout_session(
    *,
    email: str,
    pack_id: str,
    job_id: Optional[str] = None,
    job_token: Optional[str] = None,
) -> Dict[str, str]:
    stripe.api_key = _api_key()

    pack = get_credit_pack(pack_id)
    normalized_email = normalize_billing_email(email)
    success_params = {
        "success": "1",
        "session_id": "{CHECKOUT_SESSION_ID}",
        "email": normalized_email,
        "pack": pack.id,
    }
    cancel_params = {
        "canceled": "1",
        "email": normalized_email,
        "pack": pack.id,
    }
    if job_id and job_token:
        success_params["job"] = job_id
        success_params["t"] = job_token
        cancel_params["job"] = job_id
        cancel_params["t"] = job_token

    success_url = f"{_frontend_base_url()}/billing?{urlencode(success_params)}"
    cancel_url = f"{_frontend_base_url()}/billing?{urlencode(cancel_params)}"

    session = stripe.checkout.Session.create(
        mode="payment",
        customer_email=normalized_email,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "email": normalized_email,
            "pack_id": pack.id,
            "credits_minutes": str(pack.credits_minutes),
            "job_id": job_id or "",
        },
        line_items=[
            {
                "quantity": 1,
                "price_data": {
                    "currency": "usd",
                    "unit_amount": pack.price_cents,
                    "product_data": {
                        "name": pack.name,
                        "description": f"{pack.credits_minutes} transcription minutes",
                    },
                },
            }
        ],
        allow_promotion_codes=True,
    )
    return {
        "id": session["id"],
        "url": session["url"],
    }


def construct_webhook_event(payload: bytes, signature: str):
    return stripe.Webhook.construct_event(
        payload=payload,
        sig_header=signature,
        secret=_webhook_secret(),
    )
