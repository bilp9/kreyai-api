from __future__ import annotations

import base64
import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import urlencode

import stripe
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from google.cloud import firestore

from app.services.credits import is_valid_billing_email, normalize_billing_email
from app.services.stripe_billing import stripe_checkout_is_configured, stripe_webhook_is_configured

db = firestore.Client()
LICENSE_COLLECTION = "dekk_licenses"
DOWNLOAD_EVENT_COLLECTION = "dekk_download_events"
LICENSE_PREFIX = "DEKK1"
PRODUCT_ID = "dekk"


@dataclass(frozen=True)
class DekkPlan:
    id: str
    name: str
    price_cents: int
    label: str
    description: str


DEKK_PLANS: Dict[str, DekkPlan] = {
    "personal": DekkPlan(
        id="personal",
        name="Dekk Personal",
        price_cents=3900,
        label="Individual",
        description="One-time Dekk license for one person.",
    ),
    "business": DekkPlan(
        id="business",
        name="Dekk Business",
        price_cents=8900,
        label="Commercial",
        description="One-time Dekk license for commercial use by one named user or workstation.",
    ),
}

DEKK_PARTNER_PLAN = DekkPlan(
    id="linguist_partner",
    name="Dekk Linguist Partner",
    price_cents=0,
    label="Complimentary",
    description="Complimentary permanent Dekk license for the KreyAI Linguist Partner Program.",
)


def _frontend_base_url() -> str:
    return os.getenv("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")


def _api_key() -> str:
    value = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not value:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    return value


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def list_dekk_plans() -> List[Dict[str, object]]:
    return [
        {
            **asdict(plan),
            "price_usd": f"{plan.price_cents / 100:.2f}",
        }
        for plan in DEKK_PLANS.values()
    ]


def get_dekk_plan(plan_id: str) -> DekkPlan:
    normalized = str(plan_id or "").strip().lower()
    plan = DEKK_PLANS.get(normalized)
    if normalized == DEKK_PARTNER_PLAN.id:
        plan = DEKK_PARTNER_PLAN
    if not plan:
        raise ValueError("Unknown Dekk plan")
    return plan


def dekk_private_key_is_configured() -> bool:
    return bool(os.getenv("DEKK_LICENSE_PRIVATE_KEY", "").strip())


def dekk_checkout_is_configured() -> bool:
    return stripe_checkout_is_configured() and dekk_private_key_is_configured()


def dekk_webhook_is_configured() -> bool:
    return stripe_webhook_is_configured()


def _private_key() -> Ed25519PrivateKey:
    value = os.getenv("DEKK_LICENSE_PRIVATE_KEY", "").strip()
    if not value:
        raise RuntimeError("DEKK_LICENSE_PRIVATE_KEY is not configured")
    return Ed25519PrivateKey.from_private_bytes(b64url_decode(value))


def make_license_payload(*, email: str, plan_id: str, seats: int | None = None) -> dict[str, Any]:
    plan = get_dekk_plan(plan_id)
    payload: dict[str, Any] = {
        "product": PRODUCT_ID,
        "license_id": f"dekk_{uuid.uuid4().hex[:16]}",
        "email": normalize_billing_email(email),
        "plan": plan.id,
        "issued_at": to_iso(utc_now()),
        "major_version": int(os.getenv("DEKK_LICENSE_MAJOR_VERSION", "1")),
    }
    if seats is not None:
        payload["seats"] = int(seats)
    return payload


def sign_license_payload(payload: dict[str, Any]) -> str:
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = _private_key().sign(payload_bytes)
    return f"{LICENSE_PREFIX}.{b64url_encode(payload_bytes)}.{b64url_encode(signature)}"


def create_dekk_checkout_session(*, email: str, plan_id: str) -> Dict[str, str]:
    stripe.api_key = _api_key()
    normalized_email = normalize_billing_email(email)
    if not is_valid_billing_email(normalized_email):
        raise ValueError("A valid email is required.")
    plan = get_dekk_plan(plan_id)

    success_url = f"{_frontend_base_url()}/dekk?{urlencode({'success': '1', 'email': normalized_email, 'plan': plan.id})}#download"
    cancel_url = f"{_frontend_base_url()}/dekk?{urlencode({'canceled': '1', 'email': normalized_email, 'plan': plan.id})}"

    session = stripe.checkout.Session.create(
        mode="payment",
        customer_email=normalized_email,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "product": PRODUCT_ID,
            "email": normalized_email,
            "plan": plan.id,
        },
        line_items=[
            {
                "quantity": 1,
                "price_data": {
                    "currency": "usd",
                    "unit_amount": plan.price_cents,
                    "product_data": {
                        "name": plan.name,
                        "description": plan.description,
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


def issue_dekk_license_for_checkout(
    *,
    session_id: str,
    email: str,
    plan_id: str,
    amount_total: int | None = None,
    stripe_customer_id: str | None = None,
) -> dict[str, Any]:
    normalized_email = normalize_billing_email(email)
    if not is_valid_billing_email(normalized_email):
        raise ValueError("A valid email is required.")
    plan = get_dekk_plan(plan_id)
    doc_ref = db.collection(LICENSE_COLLECTION).document(session_id)
    snap = doc_ref.get()
    if snap.exists:
        data = snap.to_dict() or {}
        return {**data, "applied": False}

    payload = make_license_payload(email=normalized_email, plan_id=plan.id)
    license_key = sign_license_payload(payload)
    record = {
        "email": normalized_email,
        "plan": plan.id,
        "plan_name": plan.name,
        "license_id": payload["license_id"],
        "license_key": license_key,
        "payload": payload,
        "stripe_session_id": session_id,
        "stripe_customer_id": stripe_customer_id,
        "amount_total": amount_total,
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    doc_ref.set(record)
    return {**record, "applied": True}


def issue_dekk_partner_license(
    *,
    participant_id: str,
    email: str,
    participant_name: str | None = None,
    cohort: str = "2026",
    issued_by: str | None = None,
) -> dict[str, Any]:
    """Issue an idempotent complimentary production license without Stripe."""
    normalized_email = normalize_billing_email(email)
    if not is_valid_billing_email(normalized_email):
        raise ValueError("A valid email is required.")

    normalized_participant_id = str(participant_id or "").strip()
    if not normalized_participant_id:
        raise ValueError("A participant ID is required.")

    plan = DEKK_PARTNER_PLAN
    record_id = f"partner_{normalized_participant_id}"
    doc_ref = db.collection(LICENSE_COLLECTION).document(record_id)
    snap = doc_ref.get()
    if snap.exists:
        data = snap.to_dict() or {}
        return {**data, "applied": False}

    payload = make_license_payload(email=normalized_email, plan_id=plan.id, seats=2)
    payload.update(
        {
            "license_name": "Linguist Partner License",
            "program": "kreyai_linguist_partner",
            "participant_id": normalized_participant_id,
            "cohort": str(cohort or "2026").strip(),
            "max_devices": 2,
        }
    )
    license_key = sign_license_payload(payload)
    record = {
        "email": normalized_email,
        "participant_name": str(participant_name or "").strip() or None,
        "participant_id": normalized_participant_id,
        "program": "kreyai_linguist_partner",
        "cohort": payload["cohort"],
        "source": "complimentary_partner_program",
        "issued_by": str(issued_by or "").strip() or None,
        "plan": plan.id,
        "plan_name": plan.name,
        "license_id": payload["license_id"],
        "license_key": license_key,
        "payload": payload,
        "amount_total": 0,
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    doc_ref.set(record)
    return {**record, "applied": True}


def revoke_dekk_partner_license(
    *, participant_id: str, revoked_by: str | None = None, reason: str | None = None
) -> dict[str, Any]:
    """Record revocation; distributed Dekk keys remain offline-verifiable."""
    normalized_participant_id = str(participant_id or "").strip()
    if not normalized_participant_id:
        raise ValueError("A participant ID is required.")

    doc_ref = db.collection(LICENSE_COLLECTION).document(f"partner_{normalized_participant_id}")
    snap = doc_ref.get()
    if not snap.exists:
        return {"found": False, "revoked": False, "enforcement": "administrative_offline"}

    record = snap.to_dict() or {}
    record.update(
        {
            "status": "revoked",
            "revoked_by": str(revoked_by or "").strip() or None,
            "revocation_reason": str(reason or "").strip() or None,
            "revoked_at": firestore.SERVER_TIMESTAMP,
        }
    )
    doc_ref.set(record)
    return {
        "found": True,
        "revoked": True,
        "license_id": str(record.get("license_id") or ""),
        "enforcement": "administrative_offline",
    }


def record_dekk_download_event(
    *,
    version: str | None = None,
    platform: str | None = None,
    source: str | None = None,
    ip_hash: str | None = None,
    user_agent_hash: str | None = None,
    referer: str | None = None,
) -> dict[str, Any]:
    record = {
        "product": PRODUCT_ID,
        "version": (version or "").strip() or None,
        "platform": (platform or "").strip().lower() or "macos",
        "source": (source or "").strip().lower() or "website",
        "ip_hash": (ip_hash or "").strip() or None,
        "user_agent_hash": (user_agent_hash or "").strip() or None,
        "referer": (referer or "").strip()[:500] or None,
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    _, doc_ref = db.collection(DOWNLOAD_EVENT_COLLECTION).add(record)
    return {"id": doc_ref.id, "recorded": True}


def get_dekk_download_summary(limit: int = 5000) -> dict[str, Any]:
    limit = max(1, min(int(limit), 10000))
    query = (
        db.collection(DOWNLOAD_EVENT_COLLECTION)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    events = [doc.to_dict() or {} for doc in query.stream()]

    by_version: dict[str, int] = {}
    by_platform: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for event in events:
        version = str(event.get("version") or "unknown")
        platform = str(event.get("platform") or "unknown")
        source = str(event.get("source") or "unknown")
        by_version[version] = by_version.get(version, 0) + 1
        by_platform[platform] = by_platform.get(platform, 0) + 1
        by_source[source] = by_source.get(source, 0) + 1

    return {
        "total": len(events),
        "sample_limit": limit,
        "by_version": by_version,
        "by_platform": by_platform,
        "by_source": by_source,
    }
