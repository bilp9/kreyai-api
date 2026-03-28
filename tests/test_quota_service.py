import json

import pytest
from fastapi import HTTPException

from app.models.user import User
from app.services import quota as quota_service


def test_file_quota_store_persists_usage(tmp_path):
    store = quota_service.FileQuotaStore(data_path=tmp_path / "quotas.json")
    user = User(id="user-1", plan="free")

    initial = store.get_quota(user)
    assert initial.limit_seconds == quota_service.DEFAULT_FREE_TIER_SECONDS
    assert initial.used_seconds == 0

    store.consume_quota(user, 120)
    after = store.get_quota(user)

    assert after.used_seconds == 120
    assert after.remaining == quota_service.DEFAULT_FREE_TIER_SECONDS - 120

    saved = json.loads((tmp_path / "quotas.json").read_text())
    assert saved["user-1"]["used_seconds"] == 120


def test_file_quota_store_honors_plan_limit_env(tmp_path, monkeypatch):
    store = quota_service.FileQuotaStore(data_path=tmp_path / "quotas.json")
    user = User(id="user-2", plan="soft-launch")
    monkeypatch.setenv("QUOTA_LIMIT_SOFT_LAUNCH", "7200")

    quota = store.get_quota(user)

    assert quota.limit_seconds == 7200


def test_file_quota_store_rejects_overages(tmp_path):
    store = quota_service.FileQuotaStore(data_path=tmp_path / "quotas.json")
    user = User(id="user-3", plan="free")

    with pytest.raises(HTTPException) as exc:
        store.consume_quota(user, quota_service.DEFAULT_FREE_TIER_SECONDS + 1)

    assert exc.value.status_code == 429
    assert exc.value.detail == "Quota exceeded"


def test_get_quota_store_uses_file_backend_when_requested(monkeypatch):
    monkeypatch.setenv("KREYAI_QUOTA_BACKEND", "file")
    quota_service.reset_quota_store()

    store = quota_service.get_quota_store()

    assert isinstance(store, quota_service.FileQuotaStore)


def test_get_quota_store_falls_back_to_file_backend_in_auto_mode(monkeypatch):
    monkeypatch.setenv("KREYAI_QUOTA_BACKEND", "auto")
    quota_service.reset_quota_store()

    class BrokenFirestoreQuotaStore:
        def __init__(self, collection: str = "quotas"):
            raise RuntimeError("firestore unavailable")

    monkeypatch.setattr(quota_service, "FirestoreQuotaStore", BrokenFirestoreQuotaStore)

    store = quota_service.get_quota_store()

    assert isinstance(store, quota_service.FileQuotaStore)


def test_file_quota_store_rejects_negative_usage(tmp_path):
    store = quota_service.FileQuotaStore(data_path=tmp_path / "quotas.json")
    user = User(id="user-4", plan="free")

    with pytest.raises(HTTPException) as exc:
        store.consume_quota(user, -1)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Quota usage cannot be negative"
