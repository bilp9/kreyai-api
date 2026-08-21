from __future__ import annotations

import hashlib
from typing import Any

from google.cloud import firestore

from app.services.credits import is_valid_billing_email, normalize_billing_email


COLLECTION = "linguist_partner_applications"
ALLOWED_PRODUCTS = {"atelier", "dekk"}
ALLOWED_PLATFORMS = {"macos", "windows", "both"}
ALLOWED_EXPERIENCE = {"new", "1-3", "4-7", "8+"}

db = firestore.Client()


def _clean_text(value: str | None, *, max_length: int) -> str:
    return " ".join(str(value or "").strip().split())[:max_length]


def _clean_list(values: list[str], *, allowed: set[str] | None = None) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        item = _clean_text(value, max_length=80).lower()
        if not item or item in cleaned:
            continue
        if allowed is not None and item not in allowed:
            raise ValueError(f"Unsupported selection: {item}")
        cleaned.append(item)
    return cleaned


def save_linguist_partner_application(
    *,
    name: str,
    email: str,
    languages: str,
    products: list[str],
    platform: str,
    experience: str,
    current_tools: str | None,
    testing_interests: str,
    feedback_commitment: bool,
    privacy_consent: bool,
    source: str = "website",
) -> dict[str, Any]:
    normalized_email = normalize_billing_email(email)
    if not is_valid_billing_email(normalized_email):
        raise ValueError("A valid email is required.")

    cleaned_name = _clean_text(name, max_length=120)
    cleaned_languages = _clean_text(languages, max_length=300)
    cleaned_products = _clean_list(products, allowed=ALLOWED_PRODUCTS)
    cleaned_platform = _clean_text(platform, max_length=20).lower()
    cleaned_experience = _clean_text(experience, max_length=20).lower()
    cleaned_interests = _clean_text(testing_interests, max_length=1500)

    if len(cleaned_name) < 2:
        raise ValueError("Your name is required.")
    if not cleaned_languages:
        raise ValueError("Please list at least one working language.")
    if not cleaned_products:
        raise ValueError("Select at least one product.")
    if cleaned_platform not in ALLOWED_PLATFORMS:
        raise ValueError("Select macOS, Windows, or both.")
    if cleaned_experience not in ALLOWED_EXPERIENCE:
        raise ValueError("Select your professional experience level.")
    if len(cleaned_interests) < 20:
        raise ValueError("Tell us briefly what you would like to test.")
    if not feedback_commitment or not privacy_consent:
        raise ValueError("Program and privacy consent are required.")

    application_id = hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()[:24]
    record = {
        "application_id": application_id,
        "name": cleaned_name,
        "email": normalized_email,
        "languages": cleaned_languages,
        "products": cleaned_products,
        "platform": cleaned_platform,
        "experience": cleaned_experience,
        "current_tools": _clean_text(current_tools, max_length=500),
        "testing_interests": cleaned_interests,
        "feedback_commitment": True,
        "privacy_consent": True,
        "source": _clean_text(source, max_length=80) or "website",
        "status": "pending",
        "updated_at": firestore.SERVER_TIMESTAMP,
    }
    doc_ref = db.collection(COLLECTION).document(application_id)
    existing = doc_ref.get()
    if not existing.exists:
        record["created_at"] = firestore.SERVER_TIMESTAMP
    doc_ref.set(record, merge=True)
    return {
        "application_id": application_id,
        "status": "pending",
        "email": normalized_email,
        "name": cleaned_name,
        "products": cleaned_products,
    }


def list_linguist_partner_applications(*, limit: int = 50) -> list[dict[str, Any]]:
    query = (
        db.collection(COLLECTION)
        .order_by("updated_at", direction=firestore.Query.DESCENDING)
        .limit(max(1, min(int(limit), 200)))
    )
    return [snapshot.to_dict() or {} for snapshot in query.stream()]
