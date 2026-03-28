from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, cast
import json
import os
import threading


DEFAULT_PARTNER_TERM_DAYS = 180
FILE_DATA_PATH = Path("data/partner_plans.json")
FILE_LOCK = threading.Lock()

_STORE: Optional["PartnerPlanStore"] = None
_STORE_LOCK = threading.Lock()


@dataclass
class PartnerPlan:
    type: str = "partner"
    unlimited: bool = True
    expires_at: str = ""
    approved_at: str = ""
    renewed_at: Optional[str] = None
    notes: Optional[str] = None
    approved_by: Optional[str] = None


class PartnerPlanStore(Protocol):
    def get_plan(self, email: str) -> Optional[PartnerPlan]:
        ...

    def upsert_plan(self, email: str, plan: PartnerPlan) -> PartnerPlan:
        ...

    def delete_plan(self, email: str) -> None:
        ...


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


def _normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def _resolve_file_data_path() -> Path:
    configured_path = os.getenv("PARTNER_PLAN_FILE_PATH")
    if configured_path:
        return Path(configured_path)
    return FILE_DATA_PATH


def _term_days() -> int:
    raw_value = os.getenv("PARTNER_PLAN_TERM_DAYS")
    if raw_value:
        try:
            return max(1, int(raw_value))
        except ValueError:
            pass
    return DEFAULT_PARTNER_TERM_DAYS


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _plan_from_record(record: Optional[Dict[str, Any]]) -> Optional[PartnerPlan]:
    if not isinstance(record, dict):
        return None

    plan_type = str(record.get("type") or "partner").strip() or "partner"
    unlimited = bool(record.get("unlimited", True))
    expires_at = str(record.get("expires_at") or "").strip()
    approved_at = str(record.get("approved_at") or "").strip()
    renewed_at_raw = record.get("renewed_at")
    renewed_at = str(renewed_at_raw).strip() if renewed_at_raw else None
    notes_raw = record.get("notes")
    notes = str(notes_raw).strip() if notes_raw else None
    approved_by_raw = record.get("approved_by")
    approved_by = str(approved_by_raw).strip() if approved_by_raw else None

    if not expires_at:
        return None

    return PartnerPlan(
        type=plan_type,
        unlimited=unlimited,
        expires_at=expires_at,
        approved_at=approved_at,
        renewed_at=renewed_at,
        notes=notes,
        approved_by=approved_by,
    )


def is_plan_active(plan: Optional[PartnerPlan], now: Optional[datetime] = None) -> bool:
    if not plan:
        return False
    expires_at = _parse_datetime(plan.expires_at)
    if expires_at is None:
        return False
    comparison_time = now or _utcnow()
    return expires_at > comparison_time


class FilePartnerPlanStore:
    def __init__(self, data_path: Optional[Path] = None):
        self.data_path = data_path or _resolve_file_data_path()
        self.lock = FILE_LOCK

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if not self.data_path.exists():
            return {}
        raw = json.loads(self.data_path.read_text())
        if not isinstance(raw, dict):
            return {}
        return raw

    def _save(self, data: Dict[str, Dict[str, Any]]) -> None:
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        self.data_path.write_text(json.dumps(data, indent=2, sort_keys=True))

    def get_plan(self, email: str) -> Optional[PartnerPlan]:
        normalized_email = _normalize_email(email)
        if not normalized_email:
            return None
        with self.lock:
            data = self._load()
            return _plan_from_record(data.get(normalized_email))

    def upsert_plan(self, email: str, plan: PartnerPlan) -> PartnerPlan:
        normalized_email = _normalize_email(email)
        with self.lock:
            data = self._load()
            data[normalized_email] = asdict(plan)
            self._save(data)
        return plan

    def delete_plan(self, email: str) -> None:
        normalized_email = _normalize_email(email)
        with self.lock:
            data = self._load()
            if normalized_email in data:
                del data[normalized_email]
                self._save(data)


class FirestorePartnerPlanStore:
    def __init__(self, collection: str = "partner_plans"):
        from google.cloud import firestore

        self.db = firestore.Client()
        self.collection = collection

    def _doc_ref(self, email: str):
        return self.db.collection(self.collection).document(_normalize_email(email))

    def get_plan(self, email: str) -> Optional[PartnerPlan]:
        normalized_email = _normalize_email(email)
        if not normalized_email:
            return None
        snap = self._doc_ref(normalized_email).get()
        if not snap.exists:
            return None
        return _plan_from_record(snap.to_dict())

    def upsert_plan(self, email: str, plan: PartnerPlan) -> PartnerPlan:
        normalized_email = _normalize_email(email)
        self._doc_ref(normalized_email).set(
            {
                "email": normalized_email,
                **asdict(plan),
                "updated_at": _utcnow_iso(),
            },
            merge=True,
        )
        return plan

    def delete_plan(self, email: str) -> None:
        normalized_email = _normalize_email(email)
        self._doc_ref(normalized_email).delete()


def _build_store() -> PartnerPlanStore:
    backend = os.getenv("KREYAI_PARTNER_PLAN_BACKEND", "auto").strip().lower()

    if backend == "file":
        return FilePartnerPlanStore()

    if backend in {"", "auto"}:
        try:
            collection = os.getenv("PARTNER_PLAN_COLLECTION", "partner_plans")
            return FirestorePartnerPlanStore(collection=collection)
        except Exception:
            return FilePartnerPlanStore()

    if backend != "firestore":
        raise RuntimeError(
            f"Unsupported partner plan backend '{backend}'. Use 'auto', 'file', or 'firestore'."
        )

    try:
        collection = os.getenv("PARTNER_PLAN_COLLECTION", "partner_plans")
        return FirestorePartnerPlanStore(collection=collection)
    except Exception as exc:
        raise RuntimeError(f"Unable to initialize Firestore partner plan store: {exc}") from exc


def get_partner_plan_store() -> PartnerPlanStore:
    global _STORE
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                _STORE = _build_store()
    return cast(PartnerPlanStore, _STORE)


def reset_partner_plan_store() -> None:
    global _STORE
    with _STORE_LOCK:
        _STORE = None


def get_partner_plan(email: str) -> Optional[PartnerPlan]:
    return get_partner_plan_store().get_plan(email)


def get_partner_plan_status(email: str) -> Dict[str, Any]:
    normalized_email = _normalize_email(email)
    plan = get_partner_plan(normalized_email)
    active = is_plan_active(plan)
    return {
        "email": normalized_email,
        "has_plan": plan is not None,
        "active": active,
        "plan": asdict(plan) if plan else None,
    }


def grant_partner_plan(
    email: str,
    *,
    approved_by: Optional[str] = None,
    notes: Optional[str] = None,
    now: Optional[datetime] = None,
) -> PartnerPlan:
    current_time = now or _utcnow()
    plan = PartnerPlan(
        type="partner",
        unlimited=True,
        approved_at=current_time.isoformat(),
        expires_at=(current_time + timedelta(days=_term_days())).isoformat(),
        renewed_at=None,
        notes=notes,
        approved_by=approved_by,
    )
    return get_partner_plan_store().upsert_plan(email, plan)


def renew_partner_plan(
    email: str,
    *,
    approved_by: Optional[str] = None,
    notes: Optional[str] = None,
    now: Optional[datetime] = None,
) -> PartnerPlan:
    current_time = now or _utcnow()
    existing_plan = get_partner_plan(email)
    current_expiry = _parse_datetime(existing_plan.expires_at) if existing_plan else None
    base_time = current_expiry if current_expiry and current_expiry > current_time else current_time

    plan = PartnerPlan(
        type="partner",
        unlimited=True,
        approved_at=existing_plan.approved_at if existing_plan and existing_plan.approved_at else current_time.isoformat(),
        expires_at=(base_time + timedelta(days=_term_days())).isoformat(),
        renewed_at=current_time.isoformat(),
        notes=notes if notes is not None else (existing_plan.notes if existing_plan else None),
        approved_by=approved_by if approved_by is not None else (existing_plan.approved_by if existing_plan else None),
    )
    return get_partner_plan_store().upsert_plan(email, plan)


def revoke_partner_plan(email: str) -> Dict[str, Any]:
    existing_plan = get_partner_plan(email)
    get_partner_plan_store().delete_plan(email)
    return {
        "email": _normalize_email(email),
        "revoked": existing_plan is not None,
        "previous_plan": asdict(existing_plan) if existing_plan else None,
    }
