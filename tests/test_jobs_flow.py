import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import jobs as jobs_routes


class FakeStorage:
    def __init__(self):
        self.existing_paths = set()

    def upload_blob_path(self, job_id: str, filename: str) -> str:
        path = f"jobs/{job_id}/uploads/{filename}"
        self.existing_paths.add(path)
        return path

    def generate_resumable_start_url(self, blob_path: str, content_type: str) -> str:
        return f"https://upload.example.test/start?blob={blob_path}&type={content_type}"

    def get_download_url(self, job_id: str, filename: str) -> str:
        return f"https://download.example.test/{job_id}/{filename}"

    def blob_exists(self, blob_path: str) -> bool:
        return blob_path in self.existing_paths


@pytest.fixture(autouse=True)
def reset_public_rate_limits():
    jobs_routes._PUBLIC_RATE_LIMITS.clear()
    yield
    jobs_routes._PUBLIC_RATE_LIMITS.clear()


def test_customer_job_flow(monkeypatch):
    app = FastAPI()
    app.include_router(jobs_routes.router)

    jobs = {}
    events = {}
    dispatched = []
    sent_emails = []
    storage = FakeStorage()

    def create_job(job):
        jobs[job["job_id"]] = dict(job)

    def get_job(job_id):
        job = jobs.get(job_id)
        return dict(job) if job else None

    def update_job(job_id, updates):
        jobs[job_id].update(dict(updates))

    def record_event(job_id, event_type, message, status):
        events.setdefault(job_id, []).append(
            {
                "type": event_type,
                "message": message,
                "status": status,
            }
        )

    def get_events(job_id):
        return list(reversed(events.get(job_id, [])))

    async def send_verification_email(email, job_id, code):
        sent_emails.append({"email": email, "job_id": job_id, "code": code})

    monkeypatch.setenv("JOB_TOKEN_SECRET", "test-secret-1234567890")
    monkeypatch.setattr(jobs_routes, "fs_create_job", create_job)
    monkeypatch.setattr(jobs_routes, "fs_get_job", get_job)
    monkeypatch.setattr(jobs_routes, "fs_update_job", update_job)
    monkeypatch.setattr(jobs_routes, "record_event", record_event)
    monkeypatch.setattr(jobs_routes, "get_events", get_events)
    monkeypatch.setattr(jobs_routes, "dispatch_job", lambda job_id: dispatched.append(job_id))
    monkeypatch.setattr(jobs_routes, "send_verification_email", send_verification_email)
    monkeypatch.setattr(jobs_routes, "get_storage", lambda: storage)

    client = TestClient(app)

    create_res = client.post(
        "/api/",
        json={
            "email": "customer@example.com",
            "language": "ht",
            "accepted_terms": True,
        },
    )
    assert create_res.status_code == 200
    create_body = create_res.json()
    job_id = create_body["job_id"]
    assert "create_job;dur=" in create_res.headers["server-timing"]
    assert jobs[job_id]["status"] == "pending_verification"
    assert jobs[job_id]["verification_expires_at"]
    assert sent_emails == [
        {
            "email": "customer@example.com",
            "job_id": job_id,
            "code": jobs[job_id]["verification_code"],
        }
    ]

    verify_res = client.post(
        "/api/verify",
        params={"job_id": job_id, "code": jobs[job_id]["verification_code"]},
    )
    assert verify_res.status_code == 200
    token = verify_res.json()["access_token"]
    assert token
    assert jobs[job_id]["status"] == "verified"
    assert jobs[job_id]["verification_code"] is None

    upload_res = client.post(
        f"/api/jobs/{job_id}/upload-url",
        params={"filename": "audio.wav", "content_type": "audio/wav", "t": token},
    )
    assert upload_res.status_code == 200
    assert upload_res.json()["upload_path"] == f"jobs/{job_id}/uploads/audio.wav"

    finalize_res = client.post(
        f"/api/jobs/{job_id}/finalize-upload?t={token}",
        json={
            "file_path": f"jobs/{job_id}/uploads/audio.wav",
            "size_bytes": 12345,
            "content_type": "audio/wav",
        },
    )
    assert finalize_res.status_code == 200
    assert jobs[job_id]["status"] == "queued"
    assert dispatched == [job_id]

    status_res = client.get(f"/api/jobs/{job_id}", params={"t": token})
    assert status_res.status_code == 200
    assert status_res.json()["file_path"] == f"jobs/{job_id}/uploads/audio.wav"

    events_res = client.get(f"/api/jobs/{job_id}/events", params={"t": token})
    assert events_res.status_code == 200
    assert [event["type"] for event in events_res.json()] == [
        "uploaded",
        "verified",
        "job_created",
    ]

    download_res = client.get(
        f"/api/jobs/{job_id}/html",
        params={"t": token},
        follow_redirects=False,
    )
    assert download_res.status_code == 302
    assert (
        download_res.headers["location"]
        == f"https://download.example.test/{job_id}/transcript.html"
    )


def test_create_job_rejects_invalid_email(monkeypatch):
    app = FastAPI()
    app.include_router(jobs_routes.router)

    monkeypatch.setattr(jobs_routes, "fs_create_job", lambda job: None)
    monkeypatch.setattr(jobs_routes, "record_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(jobs_routes, "send_verification_email", lambda *args, **kwargs: None)

    client = TestClient(app)
    res = client.post(
        "/api/",
        json={
            "email": "not-an-email",
            "language": "auto",
            "accepted_terms": True,
        },
    )

    assert res.status_code == 400
    assert res.json()["detail"] == "Please enter a valid email address."


def test_finalize_upload_rejects_path_from_another_job(monkeypatch):
    app = FastAPI()
    app.include_router(jobs_routes.router)

    job_id = "KR-TEST01"
    jobs = {
        job_id: {
            "job_id": job_id,
            "verification_code": "123456",
            "verified": True,
            "status": "verified",
        }
    }

    storage = FakeStorage()
    storage.existing_paths.add("jobs/KR-OTHER/uploads/audio.wav")

    monkeypatch.setenv("JOB_TOKEN_SECRET", "test-secret-1234567890")
    monkeypatch.setattr(jobs_routes, "fs_get_job", lambda requested_job_id: dict(jobs[requested_job_id]))
    monkeypatch.setattr(jobs_routes, "fs_update_job", lambda requested_job_id, updates: jobs[requested_job_id].update(dict(updates)))
    monkeypatch.setattr(jobs_routes, "get_storage", lambda: storage)

    client = TestClient(app)
    token = jobs_routes.mint_job_token(jobs_routes._token_cfg(), job_id=job_id)

    res = client.post(
        f"/api/jobs/{job_id}/finalize-upload?t={token}",
        json={
            "file_path": "jobs/KR-OTHER/uploads/audio.wav",
            "size_bytes": 12345,
            "content_type": "audio/wav",
        },
    )

    assert res.status_code == 400
    assert res.json()["detail"] == "Upload path does not belong to this job."
    assert jobs[job_id]["status"] == "verified"


def test_finalize_upload_rolls_back_when_dispatch_fails(monkeypatch):
    app = FastAPI()
    app.include_router(jobs_routes.router)

    job_id = "KR-TEST02"
    file_path = f"jobs/{job_id}/uploads/audio.wav"
    jobs = {
        job_id: {
            "job_id": job_id,
            "verification_code": "123456",
            "verified": True,
            "status": "verified",
        }
    }

    storage = FakeStorage()
    storage.existing_paths.add(file_path)

    monkeypatch.setenv("JOB_TOKEN_SECRET", "test-secret-1234567890")
    monkeypatch.setattr(jobs_routes, "fs_get_job", lambda requested_job_id: dict(jobs[requested_job_id]))
    monkeypatch.setattr(jobs_routes, "fs_update_job", lambda requested_job_id, updates: jobs[requested_job_id].update(dict(updates)))
    monkeypatch.setattr(jobs_routes, "record_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(jobs_routes, "get_storage", lambda: storage)
    monkeypatch.setattr(jobs_routes, "dispatch_job", lambda requested_job_id: (_ for _ in ()).throw(RuntimeError("dispatch down")))

    client = TestClient(app)
    token = jobs_routes.mint_job_token(jobs_routes._token_cfg(), job_id=job_id)

    res = client.post(
        f"/api/jobs/{job_id}/finalize-upload?t={token}",
        json={
            "file_path": file_path,
            "size_bytes": 12345,
            "content_type": "audio/wav",
        },
    )

    assert res.status_code == 503
    assert res.json()["detail"] == "Upload received, but processing could not be started. Please try again."
    assert jobs[job_id]["status"] == "verified"
    assert jobs[job_id]["dispatch_error"] == "dispatch down"


def test_verify_requires_token_configuration(monkeypatch):
    app = FastAPI()
    app.include_router(jobs_routes.router)

    jobs = {
        "KR-ABC123": {
            "job_id": "KR-ABC123",
            "verification_code": "654321",
            "status": "pending_verification",
        }
    }

    monkeypatch.delenv("JOB_TOKEN_SECRET", raising=False)
    monkeypatch.setattr(jobs_routes, "fs_get_job", lambda job_id: dict(jobs[job_id]))
    monkeypatch.setattr(jobs_routes, "fs_update_job", lambda job_id, updates: jobs[job_id].update(dict(updates)))
    monkeypatch.setattr(jobs_routes, "record_event", lambda *args, **kwargs: None)

    client = TestClient(app)
    res = client.post("/api/verify", params={"job_id": "KR-ABC123", "code": "654321"})

    assert res.status_code == 503
    assert res.json()["detail"] == "Job access tokens are not configured."


def test_verify_rejects_expired_code(monkeypatch):
    app = FastAPI()
    app.include_router(jobs_routes.router)

    jobs = {
        "KR-EXP123": {
            "job_id": "KR-EXP123",
            "verification_code": "654321",
            "verification_expires_at": "2000-01-01T00:00:00+00:00",
            "status": "pending_verification",
            "verified": False,
        }
    }

    monkeypatch.setattr(jobs_routes, "fs_get_job", lambda job_id: dict(jobs[job_id]))
    monkeypatch.setattr(jobs_routes, "fs_update_job", lambda job_id, updates: jobs[job_id].update(dict(updates)))

    client = TestClient(app)
    res = client.post("/api/verify", params={"job_id": "KR-EXP123", "code": "654321"})

    assert res.status_code == 410
    assert res.json()["detail"] == "Verification code expired. Please start again."
    assert jobs["KR-EXP123"]["status"] == "expired"
    assert jobs["KR-EXP123"]["status_message"] == "Verification code expired"


def test_create_job_rejects_language_not_publicly_enabled(monkeypatch):
    app = FastAPI()
    app.include_router(jobs_routes.router)

    monkeypatch.setenv("KREYAI_PUBLIC_API_VERSION", "2.0.0")
    monkeypatch.setenv("KREYAI_PUBLIC_LANGUAGES", "auto,en,es,fr,pt,ht")

    client = TestClient(app)
    res = client.post(
        "/api/",
        json={
            "email": "customer@example.com",
            "language": "de",
            "accepted_terms": True,
        },
    )

    assert res.status_code == 400
    assert "API v2.0.0" in res.json()["detail"]
    assert "en, es, fr, pt, ht, auto" in res.json()["detail"]


def test_create_job_accepts_language_enabled_by_config(monkeypatch):
    app = FastAPI()
    app.include_router(jobs_routes.router)

    jobs = {}
    sent_emails = []

    def create_job(job):
        jobs[job["job_id"]] = dict(job)

    async def send_verification_email(email, job_id, code):
        sent_emails.append({"email": email, "job_id": job_id, "code": code})

    monkeypatch.setenv("KREYAI_PUBLIC_LANGUAGES", "auto,en,es,fr,pt,ht,de")
    monkeypatch.setattr(jobs_routes, "fs_create_job", create_job)
    monkeypatch.setattr(jobs_routes, "record_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(jobs_routes, "send_verification_email", send_verification_email)

    client = TestClient(app)
    res = client.post(
        "/api/",
        json={
            "email": "customer@example.com",
            "language": "de",
            "accepted_terms": True,
        },
    )

    assert res.status_code == 200
    job_id = res.json()["job_id"]
    assert jobs[job_id]["language"] == "de"
    assert sent_emails[0]["job_id"] == job_id


def test_public_config_exposes_enabled_languages(monkeypatch):
    app = FastAPI()
    app.include_router(jobs_routes.router)

    monkeypatch.setenv("KREYAI_PUBLIC_API_VERSION", "2.1.0")
    monkeypatch.setenv("KREYAI_PUBLIC_LANGUAGES", "auto,en,ht,de")

    client = TestClient(app)
    res = client.get("/api/public-config")

    assert res.status_code == 200
    body = res.json()
    assert body["api_version"] == "2.1.0"
    assert body["default_language"] == "auto"
    assert body["languages"] == [
        {"code": "auto", "label": "Auto Detect"},
        {"code": "en", "label": "English"},
        {"code": "ht", "label": "Haitian Creole"},
        {"code": "de", "label": "German"},
    ]


def test_public_config_hides_internal_only_languages_by_default(monkeypatch):
    app = FastAPI()
    app.include_router(jobs_routes.router)

    monkeypatch.delenv("KREYAI_PUBLIC_LANGUAGES", raising=False)

    client = TestClient(app)
    res = client.get("/api/public-config")

    assert res.status_code == 200
    assert res.json()["languages"] == [
        {"code": "auto", "label": "Auto Detect"},
        {"code": "en", "label": "English"},
        {"code": "es", "label": "Spanish"},
        {"code": "fr", "label": "French"},
        {"code": "pt", "label": "Portuguese"},
    ]


def test_verify_locks_after_repeated_failures(monkeypatch):
    app = FastAPI()
    app.include_router(jobs_routes.router)

    jobs = {
        "KR-LOCK01": {
            "job_id": "KR-LOCK01",
            "verification_code": "654321",
            "status": "pending_verification",
            "verification_attempts": 0,
        }
    }

    monkeypatch.setattr(jobs_routes, "fs_get_job", lambda job_id: dict(jobs[job_id]))
    monkeypatch.setattr(jobs_routes, "fs_update_job", lambda job_id, updates: jobs[job_id].update(dict(updates)))
    monkeypatch.setattr(jobs_routes, "record_event", lambda *args, **kwargs: None)
    monkeypatch.setenv("JOB_TOKEN_SECRET", "test-secret-1234567890")

    client = TestClient(app)

    for _ in range(5):
        res = client.post("/api/verify", params={"job_id": "KR-LOCK01", "code": "000000"})
        assert res.status_code == 400

    assert jobs["KR-LOCK01"]["verification_attempts"] == 5
    assert float(jobs["KR-LOCK01"]["verification_locked_until"]) > datetime.now(timezone.utc).timestamp()

    locked_res = client.post("/api/verify", params={"job_id": "KR-LOCK01", "code": "654321"})
    assert locked_res.status_code == 429
    assert "Too many verification attempts" in locked_res.json()["detail"]


def test_public_create_job_rate_limit(monkeypatch):
    app = FastAPI()
    app.include_router(jobs_routes.router)

    jobs_routes._PUBLIC_RATE_LIMITS.clear()

    jobs = {}

    def create_job(job):
        jobs[job["job_id"]] = dict(job)

    async def send_verification_email(email, job_id, code):
        return None

    monkeypatch.setattr(jobs_routes, "fs_create_job", create_job)
    monkeypatch.setattr(jobs_routes, "record_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(jobs_routes, "send_verification_email", send_verification_email)

    client = TestClient(app)

    for index in range(10):
        res = client.post(
            "/api/",
            json={
                "email": f"customer{index}@example.com",
                "language": "auto",
                "accepted_terms": True,
            },
        )
        assert res.status_code == 200

    limited_res = client.post(
        "/api/",
        json={
            "email": "customer-final@example.com",
            "language": "auto",
            "accepted_terms": True,
        },
    )
    assert limited_res.status_code == 429
    assert "Too many requests" in limited_res.json()["detail"]
