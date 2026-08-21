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
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from google.cloud import firestore

from app.services.credits import is_valid_billing_email, normalize_billing_email
from app.services.stripe_billing import stripe_checkout_is_configured, stripe_webhook_is_configured

db = firestore.Client()
LICENSE_COLLECTION = "atelier_licenses"
ACTIVATION_COLLECTION = "atelier_activations"
PRODUCT_ID = "atelier"
LICENSE_PREFIX = "ATLR1"


@dataclass(frozen=True)
class AtelierPlan:
    id: str
    name: str
    price_cents: int
    label: str
    description: str


ATELIER_PLANS: Dict[str, AtelierPlan] = {
    "classic": AtelierPlan(
        id="classic",
        name="aTelier Classic",
        price_cents=14900,
        label="One-time",
        description="One-time aTelier Classic license for one translator. Free updates, single-machine activation.",
    ),
}

ATELIER_PARTNER_PLAN = AtelierPlan(
    id="linguist_partner",
    name="aTelier Linguist Partner",
    price_cents=0,
    label="Complimentary",
    description="Complimentary permanent aTelier license for the KreyAI Linguist Partner Program.",
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


def list_atelier_plans() -> List[Dict[str, object]]:
    return [
        {
            **asdict(plan),
            "price_usd": f"{plan.price_cents / 100:.2f}",
        }
        for plan in ATELIER_PLANS.values()
    ]


def get_atelier_plan(plan_id: str) -> AtelierPlan:
    normalized = str(plan_id or "").strip().lower()
    plan = ATELIER_PLANS.get(normalized)
    if normalized == ATELIER_PARTNER_PLAN.id:
        plan = ATELIER_PARTNER_PLAN
    if not plan:
        raise ValueError("Unknown aTelier plan")
    return plan


def atelier_private_key_is_configured() -> bool:
    return bool(os.getenv("ATELIER_LICENSE_PRIVATE_KEY", "").strip())


def atelier_checkout_is_configured() -> bool:
    return stripe_checkout_is_configured() and atelier_private_key_is_configured()


def atelier_webhook_is_configured() -> bool:
    return stripe_webhook_is_configured()


def _private_key() -> Ed25519PrivateKey:
    value = os.getenv("ATELIER_LICENSE_PRIVATE_KEY", "").strip()
    if not value:
        raise RuntimeError("ATELIER_LICENSE_PRIVATE_KEY is not configured")
    return Ed25519PrivateKey.from_private_bytes(b64url_decode(value))


def make_license_payload(*, email: str, plan_id: str) -> dict[str, Any]:
    plan = get_atelier_plan(plan_id)
    return {
        "product": PRODUCT_ID,
        "license_id": f"atelier_{uuid.uuid4().hex[:16]}",
        "email": normalize_billing_email(email),
        "plan": plan.id,
        "issued_at": to_iso(utc_now()),
        "major_version": int(os.getenv("ATELIER_LICENSE_MAJOR_VERSION", "1")),
    }


def sign_license_payload(payload: dict[str, Any]) -> str:
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = _private_key().sign(payload_bytes)
    return f"{LICENSE_PREFIX}.{b64url_encode(payload_bytes)}.{b64url_encode(signature)}"


def verify_license_key(license_key: str) -> dict[str, Any] | None:
    """Verify an ATLR1.<payload>.<sig> key offline. Returns the decoded payload, or None if invalid."""
    public_key_value = os.getenv("ATELIER_LICENSE_PUBLIC_KEY", "").strip()
    if not public_key_value:
        raise RuntimeError("ATELIER_LICENSE_PUBLIC_KEY is not configured")

    try:
        prefix, payload_b64, sig_b64 = str(license_key or "").strip().split(".")
    except ValueError:
        return None
    if prefix != LICENSE_PREFIX:
        return None

    try:
        payload_bytes = b64url_decode(payload_b64)
        signature = b64url_decode(sig_b64)
        public_key = Ed25519PublicKey.from_public_bytes(b64url_decode(public_key_value))
        public_key.verify(signature, payload_bytes)
    except (InvalidSignature, ValueError):
        return None

    try:
        payload = json.loads(payload_bytes)
    except Exception:
        return None
    if payload.get("product") != PRODUCT_ID:
        return None
    return payload


def create_atelier_checkout_session(*, email: str) -> Dict[str, str]:
    stripe.api_key = _api_key()
    normalized_email = normalize_billing_email(email)
    if not is_valid_billing_email(normalized_email):
        raise ValueError("A valid email is required.")
    plan = get_atelier_plan("classic")

    success_url = f"{_frontend_base_url()}/atelier?{urlencode({'success': '1', 'email': normalized_email})}#download"
    cancel_url = f"{_frontend_base_url()}/atelier?{urlencode({'canceled': '1', 'email': normalized_email})}"

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


def issue_atelier_license_for_checkout(
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
    plan = get_atelier_plan(plan_id)
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


def issue_atelier_partner_license(
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

    plan = ATELIER_PARTNER_PLAN
    record_id = f"partner_{normalized_participant_id}"
    doc_ref = db.collection(LICENSE_COLLECTION).document(record_id)
    snap = doc_ref.get()
    if snap.exists:
        data = snap.to_dict() or {}
        return {**data, "applied": False}

    payload = make_license_payload(email=normalized_email, plan_id=plan.id)
    payload.update(
        {
            "license_name": "Linguist Partner License",
            "program": "kreyai_linguist_partner",
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


def activate_atelier_license(*, license_key: str, machine_id: str) -> dict[str, Any]:
    machine_id = str(machine_id or "").strip()
    if not machine_id:
        return {"valid": False, "error": "A machine ID is required."}

    payload = verify_license_key(license_key)
    if payload is None:
        return {"valid": False, "error": "Invalid license key."}

    license_id = payload["license_id"]
    doc_ref = db.collection(ACTIVATION_COLLECTION).document(license_id)
    snap = doc_ref.get()
    max_devices = max(1, int(payload.get("max_devices") or 1))
    if snap.exists:
        data = snap.to_dict() or {}
        active_machines = [str(value) for value in data.get("machine_ids", []) if value]
        legacy_machine = str(data.get("machine_id") or "").strip()
        if legacy_machine and legacy_machine not in active_machines:
            active_machines.insert(0, legacy_machine)
        if machine_id not in active_machines and len(active_machines) >= max_devices:
            return {
                "valid": False,
                "error": f"This license is already active on {max_devices} computer{'s' if max_devices != 1 else ''}. Deactivate one first, or contact support to transfer it.",
            }
    else:
        active_machines = []

    if machine_id not in active_machines:
        active_machines.append(machine_id)

    doc_ref.set(
        {
            "license_id": license_id,
            "machine_id": active_machines[0],
            "machine_ids": active_machines,
            "max_devices": max_devices,
            "email": payload.get("email"),
            "plan": payload.get("plan"),
            "activated_at": firestore.SERVER_TIMESTAMP,
        }
    )
    return {"valid": True, "email": payload.get("email"), "plan": payload.get("plan")}


def deactivate_atelier_license(*, license_key: str, machine_id: str) -> dict[str, Any]:
    machine_id = str(machine_id or "").strip()
    payload = verify_license_key(license_key)
    if payload is None:
        return {"valid": False, "error": "Invalid license key."}

    license_id = payload["license_id"]
    doc_ref = db.collection(ACTIVATION_COLLECTION).document(license_id)
    snap = doc_ref.get()
    if not snap.exists:
        return {"valid": True, "deactivated": False}

    data = snap.to_dict() or {}
    active_machines = [str(value) for value in data.get("machine_ids", []) if value]
    legacy_machine = str(data.get("machine_id") or "").strip()
    if legacy_machine and legacy_machine not in active_machines:
        active_machines.insert(0, legacy_machine)
    if machine_id not in active_machines:
        return {"valid": False, "error": "This license is not active on this machine."}

    remaining = [value for value in active_machines if value != machine_id]
    if remaining:
        doc_ref.set(
            {
                **data,
                "machine_id": remaining[0],
                "machine_ids": remaining,
                "deactivated_at": firestore.SERVER_TIMESTAMP,
            }
        )
    else:
        doc_ref.delete()
    return {"valid": True, "deactivated": True}
