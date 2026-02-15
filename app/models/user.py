from dataclasses import dataclass
from pathlib import Path
import json
import os
from typing import Optional

# Set path based on environment variable or absolute container path
DATA_PATH = Path(os.getenv("API_KEYS_FILE", "/app/data/api_keys.json"))

@dataclass
class User:
    id: str
    name: str = ""
    plan: str = "free"

def get_user_by_api_key(api_key: str) -> Optional[User]:
    # --- STEP 1: Check Environment Variable (Bypass file issues) ---
    env_key = os.getenv("API_KEY")
    if env_key and api_key == env_key:
        return User(id="admin-env", name="Admin User", plan="soft-launch")

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

        return User(
            id=api_key,
            name=record.get("email", ""),
            plan=record.get("plan", "free"),
        )
    except Exception as e:
        print(f"Error reading API keys: {e}")
        return None