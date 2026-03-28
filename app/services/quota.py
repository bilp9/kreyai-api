# app/services/quota.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, cast
import json
import os
import threading

from fastapi import HTTPException, status

from app.models.user import User

DEFAULT_FREE_TIER_SECONDS = 1800
FILE_DATA_PATH = Path("data/quotas.json")
FILE_LOCK = threading.Lock()

_STORE: Optional["QuotaStore"] = None
_STORE_LOCK = threading.Lock()


@dataclass
class Quota:
    limit_seconds: int
    used_seconds: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.limit_seconds - self.used_seconds)


class QuotaStore(Protocol):
    def get_quota(self, user: User) -> Quota:
        ...

    def consume_quota(self, user: User, seconds: int) -> Quota:
        ...


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_file_data_path() -> Path:
    configured_path = os.getenv("QUOTA_FILE_PATH")
    if configured_path:
        return Path(configured_path)
    return FILE_DATA_PATH


def _plan_default_limit_seconds(user: User) -> int:
    raw_value = os.getenv(f"QUOTA_LIMIT_{user.plan.upper().replace('-', '_')}")
    if raw_value:
        try:
            return max(0, int(raw_value))
        except ValueError:
            pass
    return DEFAULT_FREE_TIER_SECONDS


def _quota_from_record(record: Optional[Dict[str, Any]], user: User) -> Quota:
    data = record or {}

    limit_seconds = data.get("limit_seconds")
    try:
        limit_seconds = int(limit_seconds) if limit_seconds is not None else _plan_default_limit_seconds(user)
    except (TypeError, ValueError):
        limit_seconds = _plan_default_limit_seconds(user)

    used_seconds = data.get("used_seconds", 0)
    try:
        used_seconds = max(0, int(used_seconds))
    except (TypeError, ValueError):
        used_seconds = 0

    return Quota(limit_seconds=limit_seconds, used_seconds=used_seconds)


def _normalize_consume_seconds(seconds: int) -> int:
    try:
        normalized_seconds = int(seconds)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quota usage must be a whole number of seconds",
        ) from None

    if normalized_seconds < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quota usage cannot be negative",
        )

    return normalized_seconds


class FileQuotaStore:
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

    def get_quota(self, user: User) -> Quota:
        with self.lock:
            data = self._load()
            quota = _quota_from_record(data.get(user.id), user)
            data[user.id] = {
                "limit_seconds": quota.limit_seconds,
                "used_seconds": quota.used_seconds,
                "updated_at": _utcnow_iso(),
            }
            self._save(data)
            return quota

    def consume_quota(self, user: User, seconds: int) -> Quota:
        seconds = _normalize_consume_seconds(seconds)
        with self.lock:
            data = self._load()
            quota = _quota_from_record(data.get(user.id), user)

            if quota.remaining < seconds:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Quota exceeded",
                )

            quota.used_seconds += seconds
            data[user.id] = {
                "limit_seconds": quota.limit_seconds,
                "used_seconds": quota.used_seconds,
                "updated_at": _utcnow_iso(),
            }
            self._save(data)
            return quota


class FirestoreQuotaStore:
    def __init__(self, collection: str = "quotas"):
        from google.cloud import firestore

        self.firestore = firestore
        self.db = firestore.Client()
        self.collection = collection

    def _doc_ref(self, user_id: str):
        return self.db.collection(self.collection).document(user_id)

    def get_quota(self, user: User) -> Quota:
        snap = self._doc_ref(user.id).get()
        quota = _quota_from_record(snap.to_dict() if snap.exists else None, user)

        if not snap.exists:
            self._doc_ref(user.id).set(
                {
                    "user_id": user.id,
                    "plan": user.plan,
                    "limit_seconds": quota.limit_seconds,
                    "used_seconds": quota.used_seconds,
                    "updated_at": _utcnow_iso(),
                }
            )

        return quota

    def consume_quota(self, user: User, seconds: int) -> Quota:
        seconds = _normalize_consume_seconds(seconds)
        doc_ref = self._doc_ref(user.id)
        firestore = self.firestore

        @firestore.transactional
        def _consume(transaction):
            snap = doc_ref.get(transaction=transaction)
            quota = _quota_from_record(snap.to_dict() if snap.exists else None, user)

            if quota.remaining < seconds:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Quota exceeded",
                )

            quota.used_seconds += seconds
            transaction.set(
                doc_ref,
                {
                    "user_id": user.id,
                    "plan": user.plan,
                    "limit_seconds": quota.limit_seconds,
                    "used_seconds": quota.used_seconds,
                    "updated_at": _utcnow_iso(),
                },
                merge=True,
            )

            return quota

        return _consume(self.db.transaction())


def _build_store() -> QuotaStore:
    backend = os.getenv("KREYAI_QUOTA_BACKEND", "auto").strip().lower()

    if backend == "file":
        return FileQuotaStore()

    if backend in {"", "auto"}:
        try:
            collection = os.getenv("QUOTA_COLLECTION", "quotas")
            return FirestoreQuotaStore(collection=collection)
        except Exception:
            return FileQuotaStore()

    if backend != "firestore":
        raise RuntimeError(
            f"Unsupported quota backend '{backend}'. Use 'auto', 'file', or 'firestore'."
        )

    try:
        collection = os.getenv("QUOTA_COLLECTION", "quotas")
        return FirestoreQuotaStore(collection=collection)
    except Exception as exc:
        raise RuntimeError(f"Unable to initialize Firestore quota store: {exc}") from exc


def reset_quota_store() -> None:
    global _STORE
    with _STORE_LOCK:
        _STORE = None


def get_quota_store() -> QuotaStore:
    global _STORE
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                _STORE = _build_store()
    return cast(QuotaStore, _STORE)


def get_quota(user: User) -> Quota:
    return get_quota_store().get_quota(user)


def check_and_consume_quota(user: User, seconds: int = 60) -> None:
    get_quota_store().consume_quota(user, seconds)
