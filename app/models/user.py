from dataclasses import dataclass
from pathlib import Path
import json
import os
from typing import Any, Optional

# Set path based on environment variable or absolute container path
DATA_PATH = Path(os.getenv("API_KEYS_FILE", "/app/data/api_keys.json"))

@dataclass
class User:
    id: str
    name: str = ""
    plan: str = "free"
    active: bool = True
    email: str = ""


def _coerce_active(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled"}

def get_user_by_api_key(api_key: str) -> Optional[User]:
    # --- STEP 1: Check Environment Variable (Bypass file issues) ---
    env_key = os.getenv("API_KEY")
    if env_key:
        if api_key == env_key:
            return User(
                id="admin-env",
                name="Admin User",
                plan="soft-launch",
                active=True,
                email=os.getenv("ADMIN_EMAIL", ""),
            )
        return None

    # --- STEP 2: Check JSON File ---
    if not DATA_PATH.exists():
        # This is the message appearing in your logs
        print(f"CRITICAL: API Key file not found at {DATA_PATH}")
        return None

    try:
        data = json.loads(DATA_PATH.read_text())
        record = data.get(api_key)

        if not record:
            return None

        email = str(record.get("email", "")).strip()
        name = str(record.get("name", "")).strip() or email

        return User(
            id=api_key,
            name=name,
            plan=str(record.get("plan", "free")),
            active=_coerce_active(record.get("active", True)),
            email=email,
        )
    except Exception as e:
        print(f"Error reading API keys: {e}")
        return None
