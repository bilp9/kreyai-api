import json

import pytest
from fastapi import HTTPException

from app.auth.auth import get_current_user
from app.models import user as user_model


def test_get_user_by_api_key_defaults_active_from_file(tmp_path, monkeypatch):
    data_path = tmp_path / "api_keys.json"
    data_path.write_text(
        json.dumps(
            {
                "test-key": {
                    "email": "customer@example.com",
                    "plan": "starter",
                }
            }
        )
    )
    monkeypatch.setattr(user_model, "DATA_PATH", data_path)
    monkeypatch.delenv("API_KEY", raising=False)

    user = user_model.get_user_by_api_key("test-key")

    assert user is not None
    assert user.id == "test-key"
    assert user.email == "customer@example.com"
    assert user.name == "customer@example.com"
    assert user.plan == "starter"
    assert user.active is True


def test_get_user_by_api_key_respects_disabled_flag(tmp_path, monkeypatch):
    data_path = tmp_path / "api_keys.json"
    data_path.write_text(
        json.dumps(
            {
                "disabled-key": {
                    "email": "disabled@example.com",
                    "plan": "starter",
                    "active": False,
                }
            }
        )
    )
    monkeypatch.setattr(user_model, "DATA_PATH", data_path)
    monkeypatch.delenv("API_KEY", raising=False)

    user = user_model.get_user_by_api_key("disabled-key")

    assert user is not None
    assert user.active is False


def test_get_current_user_accepts_x_api_key(tmp_path, monkeypatch):
    data_path = tmp_path / "api_keys.json"
    data_path.write_text(
        json.dumps(
            {
                "header-key": {
                    "email": "header@example.com",
                    "plan": "starter",
                }
            }
        )
    )
    monkeypatch.setattr(user_model, "DATA_PATH", data_path)
    monkeypatch.delenv("API_KEY", raising=False)

    user = get_current_user(x_api_key="header-key")

    assert user.id == "header-key"
    assert user.active is True


def test_get_current_user_accepts_bearer_authorization(tmp_path, monkeypatch):
    data_path = tmp_path / "api_keys.json"
    data_path.write_text(
        json.dumps(
            {
                "bearer-key": {
                    "email": "bearer@example.com",
                    "plan": "starter",
                }
            }
        )
    )
    monkeypatch.setattr(user_model, "DATA_PATH", data_path)
    monkeypatch.delenv("API_KEY", raising=False)

    user = get_current_user(authorization="Bearer bearer-key")

    assert user.id == "bearer-key"
    assert user.email == "bearer@example.com"


def test_get_current_user_rejects_disabled_user(tmp_path, monkeypatch):
    data_path = tmp_path / "api_keys.json"
    data_path.write_text(
        json.dumps(
            {
                "disabled-key": {
                    "email": "disabled@example.com",
                    "active": False,
                }
            }
        )
    )
    monkeypatch.setattr(user_model, "DATA_PATH", data_path)
    monkeypatch.delenv("API_KEY", raising=False)

    with pytest.raises(HTTPException) as exc:
        get_current_user(x_api_key="disabled-key")

    assert exc.value.status_code == 403
    assert exc.value.detail == "User account is disabled"


def test_get_current_user_rejects_invalid_authorization_format():
    with pytest.raises(HTTPException) as exc:
        get_current_user(authorization="Token nope")

    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid Authorization header format"
