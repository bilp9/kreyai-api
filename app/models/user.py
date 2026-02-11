# app/models/user.py
from dataclasses import dataclass
from pathlib import Path
import json
from typing import Optional

DATA_PATH = Path("data/api_keys.json")


@dataclass
class User:
    id: str
    name: str
    plan: str = "free"


def get_user_by_api_key(api_key: str) -> Optional[User]:
    if not DATA_PATH.exists():
        return None

    data = json.loads(DATA_PATH.read_text())
    record = data.get(api_key)

    if not record:
        return None

    return User(
        id=record["id"],
        name=record.get("name", ""),
        plan=record.get("plan", "free"),
    )
