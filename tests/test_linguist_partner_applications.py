from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import linguist_partner as routes
from app.services import linguist_partner_applications as service


class Snapshot:
    def __init__(self, data=None):
        self.data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self.data or {})


class Document:
    def __init__(self, store, key):
        self.store = store
        self.key = key

    def get(self):
        return Snapshot(self.store.get(self.key))

    def set(self, value, merge=False):
        current = dict(self.store.get(self.key) or {}) if merge else {}
        current.update(value)
        self.store[self.key] = current


class Collection:
    def __init__(self, store):
        self.store = store

    def document(self, key):
        return Document(self.store, key)


class DB:
    def __init__(self):
        self.store = {}

    def collection(self, _name):
        return Collection(self.store)


def payload(**overrides):
    data = {
        "name": "Marie Linguist",
        "email": "Marie@example.com",
        "languages": "Haitian Creole, English, French",
        "products": ["atelier", "dekk"],
        "platform": "macos",
        "experience": "8+",
        "current_tools": "Trados and Express Scribe",
        "testing_interests": "I want to test translation memory and daily transcription workflows.",
        "feedback_commitment": True,
        "privacy_consent": True,
        "website": "",
    }
    data.update(overrides)
    return data


def test_application_is_stored_as_pending(monkeypatch):
    fake_db = DB()
    monkeypatch.setattr(service, "db", fake_db)
    monkeypatch.setattr(routes, "send_linguist_partner_application_email", lambda application: None)
    app = FastAPI()
    app.include_router(routes.router)

    response = TestClient(app).post("/api/linguist-partner/apply", json=payload())

    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    stored = next(iter(fake_db.store.values()))
    assert stored["email"] == "marie@example.com"
    assert stored["products"] == ["atelier", "dekk"]
    assert stored["status"] == "pending"


def test_application_requires_consent(monkeypatch):
    monkeypatch.setattr(service, "db", DB())
    app = FastAPI()
    app.include_router(routes.router)

    response = TestClient(app).post(
        "/api/linguist-partner/apply",
        json=payload(privacy_consent=False),
    )

    assert response.status_code == 400
    assert "consent" in response.json()["detail"].lower()


def test_honeypot_submission_is_not_stored(monkeypatch):
    fake_db = DB()
    monkeypatch.setattr(service, "db", fake_db)
    app = FastAPI()
    app.include_router(routes.router)

    response = TestClient(app).post(
        "/api/linguist-partner/apply",
        json=payload(website="spam.example"),
    )

    assert response.status_code == 202
    assert fake_db.store == {}
