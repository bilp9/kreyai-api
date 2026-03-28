import io

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import upload as upload_routes


def test_upload_route_uses_bearer_auth_and_duration_based_quota(monkeypatch):
    app = FastAPI()
    app.include_router(upload_routes.router)

    observed = {}

    def fake_current_user(authorization=None, x_api_key=None):
        observed["authorization"] = authorization
        observed["x_api_key"] = x_api_key
        return type("User", (), {"id": "user-123"})()

    monkeypatch.setattr(upload_routes, "_estimate_upload_seconds", lambda path: 137)
    monkeypatch.setattr(
        upload_routes,
        "check_and_consume_quota",
        lambda user, seconds: observed.setdefault("quota_seconds", seconds),
    )
    monkeypatch.setattr(
        upload_routes,
        "transcribe_audio",
        lambda path: {"text": "transcribed text"},
    )
    app.dependency_overrides[upload_routes.get_current_user] = fake_current_user

    client = TestClient(app)
    res = client.post(
        "/api/upload",
        headers={"Authorization": "Bearer bearer-key"},
        files={"file": ("sample.wav", io.BytesIO(b"fake-audio"), "audio/wav")},
    )

    assert res.status_code == 200
    assert res.json() == {
        "id": "kr_user-123",
        "text": "transcribed text",
    }
    assert observed["quota_seconds"] == 137


def test_estimate_upload_seconds_falls_back_when_duration_probe_fails(monkeypatch):
    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "app.processing.runner":
            raise RuntimeError("ffprobe unavailable")
        return original_import(name, globals, locals, fromlist, level)

    import builtins

    original_import = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert upload_routes._estimate_upload_seconds("/tmp/missing.wav") == 60
