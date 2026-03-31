from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import os
from typing import Any, Dict, Optional

from app.services.partner_plans import get_partner_plan_status
from app.services.credits import ensure_starter_credit_grant, get_credit_balance_minutes


@dataclass
class AccessDecision:
    allowed: bool
    source: str
    reason: str
    credits_to_deduct: int = 0
    billable_minutes: Optional[int] = None
    requires_credit_check: bool = False
    partner_active: bool = False
    partner_expires_at: Optional[str] = None
    available_credits: int = 0
    missing_credits: int = 0


def estimate_billable_minutes(audio_duration_seconds: Optional[float]) -> Optional[int]:
    if audio_duration_seconds is None:
        return None

    try:
        seconds = float(audio_duration_seconds)
    except (TypeError, ValueError):
        return None

    if seconds <= 0:
        return 1

    return max(1, int(math.ceil(seconds / 60.0)))


def _credits_enforced() -> bool:
    raw_value = os.getenv("KREYAI_ENFORCE_CREDITS", "")
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def resolve_submission_access(
    email: str,
    *,
    audio_duration_seconds: Optional[float] = None,
) -> AccessDecision:
    partner_access = get_partner_plan_status(email)
    partner_plan = partner_access.get("plan") or {}
    billable_minutes = estimate_billable_minutes(audio_duration_seconds)

    if partner_access.get("active"):
        return AccessDecision(
            allowed=True,
            source="plan_unlimited",
            reason="active_partner_plan",
            credits_to_deduct=0,
            billable_minutes=billable_minutes,
            requires_credit_check=False,
            partner_active=True,
            partner_expires_at=partner_plan.get("expires_at"),
            available_credits=0,
            missing_credits=0,
        )

    if _credits_enforced():
        required_credits = billable_minutes or 0
        ensure_starter_credit_grant(email)
        available_credits = get_credit_balance_minutes(email)
        missing_credits = max(0, required_credits - available_credits)
        return AccessDecision(
            allowed=available_credits >= required_credits,
            source="credits",
            reason="credits_ok" if available_credits >= required_credits else "credits_required",
            credits_to_deduct=required_credits,
            billable_minutes=billable_minutes,
            requires_credit_check=True,
            partner_active=False,
            available_credits=available_credits,
            missing_credits=missing_credits,
        )

    return AccessDecision(
        allowed=True,
        source="credits",
        reason="credits_unenforced",
        credits_to_deduct=billable_minutes or 0,
        billable_minutes=billable_minutes,
        requires_credit_check=True,
        partner_active=False,
        available_credits=0,
        missing_credits=0,
    )


def serialize_access_decision(decision: AccessDecision) -> Dict[str, Any]:
    return asdict(decision)
