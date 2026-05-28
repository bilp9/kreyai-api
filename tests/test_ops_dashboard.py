from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.auth import get_current_user
from app.routes import ops as ops_routes
from app.models.user import User


def test_ops_dashboard_returns_summary_and_jobs(monkeypatch):
    app = FastAPI()
    app.include_router(ops_routes.router)
    app.dependency_overrides[get_current_user] = lambda: User(
        id="ops-user",
        email="ops@example.com",
        plan="soft-launch",
    )

    monkeypatch.setattr(
        ops_routes,
        "list_recent_jobs",
        lambda limit=25, status=None, language=None, email_query=None, created_from=None, created_to=None: [
            {
                "job_id": "KR-001",
                "email": "a@example.com",
                "status": "completed",
                "progress": 100,
                "status_message": "Completed",
                "language": "en",
                "audio_duration_seconds": 120.0,
                "processing_time_seconds": 60.0,
                "estimated_cost_usd": 0.12,
                "realtime_factor": 0.5,
                "attempts": 1,
                "created_at": "2026-03-24T10:00:00+00:00",
                "updated_at": "2026-03-24T10:02:00+00:00",
                "completed_at": "2026-03-24T10:02:00+00:00",
            },
            {
                "job_id": "KR-002",
                "email": "b@example.com",
                "status": "failed",
                "progress": 55,
                "status_message": "Model error",
                "language": "ht",
                "estimated_cost_usd": 0.08,
                "attempts": 2,
                "created_at": "2026-03-24T11:00:00+00:00",
                "updated_at": "2026-03-24T11:05:00+00:00",
            },
        ],
    )
    monkeypatch.setattr(
        ops_routes,
        "count_jobs_by_status",
        lambda status: {
            "pending_verification": 3,
            "verified": 1,
            "uploaded": 0,
            "queued": 2,
            "processing": 1,
            "completed": 10,
            "failed": 2,
            "expired": 1,
        }[status],
    )
    monkeypatch.setattr(
        ops_routes,
        "count_jobs_by_field",
        lambda field_name, value: 0,
    )
    monkeypatch.setattr(
        ops_routes,
        "_storage_exists_for_job",
        lambda job_id: False,
    )

    client = TestClient(app)
    res = client.get("/ops/dashboard")

    assert res.status_code == 200
    body = res.json()
    assert body["viewer"]["id"] == "ops-user"
    assert body["filters"] == {
        "limit": 25,
        "status": None,
        "language": None,
        "email": None,
        "date_from": None,
        "date_to": None,
    }
    assert body["summary"]["recent_jobs_count"] == 2
    assert body["summary"]["recent_completed_jobs"] == 1
    assert body["summary"]["recent_failed_jobs"] == 1
    assert body["summary"]["recent_audio_minutes"] == 2.0
    assert body["summary"]["recent_estimated_cost_usd"] == 0.2
    assert body["summary"]["avg_processing_time_seconds"] == 60.0
    assert body["summary"]["avg_realtime_factor"] == 0.5
    assert body["summary"]["status_counts"]["completed"] == 10
    assert body["jobs"][0]["job_id"] == "KR-001"


def test_ops_dashboard_respects_limit(monkeypatch):
    app = FastAPI()
    app.include_router(ops_routes.router)
    app.dependency_overrides[get_current_user] = lambda: User(id="ops-user")

    observed = {}

    def fake_list_recent_jobs(limit=25, status=None, language=None, email_query=None, created_from=None, created_to=None):
        observed["limit"] = limit
        observed["status"] = status
        observed["language"] = language
        observed["email_query"] = email_query
        observed["created_from"] = created_from
        observed["created_to"] = created_to
        return []

    monkeypatch.setattr(ops_routes, "list_recent_jobs", fake_list_recent_jobs)
    monkeypatch.setattr(ops_routes, "count_jobs_by_status", lambda status: 0)
    monkeypatch.setattr(ops_routes, "count_jobs_by_field", lambda field_name, value: 0)

    client = TestClient(app)
    res = client.get("/ops/dashboard", params={"limit": 10})

    assert res.status_code == 200
    assert observed["limit"] == 10
    assert observed["created_from"] is None
    assert observed["created_to"] is None


def test_ops_dashboard_passes_filters(monkeypatch):
    app = FastAPI()
    app.include_router(ops_routes.router)
    app.dependency_overrides[get_current_user] = lambda: User(id="ops-user")

    observed = {}

    def fake_list_recent_jobs(limit=25, status=None, language=None, email_query=None, created_from=None, created_to=None):
        observed["limit"] = limit
        observed["status"] = status
        observed["language"] = language
        observed["email_query"] = email_query
        observed["created_from"] = created_from
        observed["created_to"] = created_to
        return []

    monkeypatch.setattr(ops_routes, "list_recent_jobs", fake_list_recent_jobs)
    monkeypatch.setattr(ops_routes, "count_jobs_by_status", lambda status: 0)
    monkeypatch.setattr(ops_routes, "count_jobs_by_field", lambda field_name, value: 0)

    client = TestClient(app)
    res = client.get(
        "/ops/dashboard",
        params={"limit": 15, "status": "failed", "language": "ht", "email": "billy"},
    )

    assert res.status_code == 200
    assert observed == {
        "limit": 15,
        "status": "failed",
        "language": "ht",
        "email_query": "billy",
        "created_from": None,
        "created_to": None,
    }


def test_ops_dashboard_passes_date_filters(monkeypatch):
    app = FastAPI()
    app.include_router(ops_routes.router)
    app.dependency_overrides[get_current_user] = lambda: User(id="ops-user")

    observed = {}

    def fake_list_recent_jobs(limit=25, status=None, language=None, email_query=None, created_from=None, created_to=None):
        observed["limit"] = limit
        observed["status"] = status
        observed["language"] = language
        observed["email_query"] = email_query
        observed["created_from"] = created_from
        observed["created_to"] = created_to
        return []

    monkeypatch.setattr(ops_routes, "list_recent_jobs", fake_list_recent_jobs)
    monkeypatch.setattr(ops_routes, "count_jobs_by_status", lambda status: 0)
    monkeypatch.setattr(ops_routes, "count_jobs_by_field", lambda field_name, value: 0)

    client = TestClient(app)
    res = client.get(
        "/ops/dashboard",
        params={"date_from": "2026-04-01", "date_to": "2026-04-10"},
    )

    assert res.status_code == 200
    assert observed["created_from"] == "2026-04-01T00:00:00+00:00"
    assert observed["created_to"] == "2026-04-10T23:59:59.999999+00:00"
