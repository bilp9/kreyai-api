# app/services/quota.py
from dataclasses import dataclass
from typing import Dict
from pathlib import Path
import json
import threading

from fastapi import HTTPException, status
from app.models.user import User

DATA_PATH = Path("data/quotas.json")
_LOCK = threading.Lock()


@dataclass
class Quota:
    limit_seconds: int
    used_seconds: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.limit_seconds - self.used_seconds)


def _load() -> Dict[str, Quota]:
    if not DATA_PATH.exists():
        return {}
    raw = json.loads(DATA_PATH.read_text())
    return {k: Quota(**v) for k, v in raw.items()}


def _save(db: Dict[str, Quota]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw = {k: vars(v) for k, v in db.items()}
    DATA_PATH.write_text(json.dumps(raw, indent=2))


def get_quota(user: User) -> Quota:
    with _LOCK:
        db = _load()
        q = db.get(user.id)

        if not q:
            q = Quota(limit_seconds=1800)  # 30 min free tier
            db[user.id] = q
            _save(db)

        return q


def check_and_consume_quota(user: User, seconds: int = 60) -> None:
    with _LOCK:
        db = _load()
        q = db.get(user.id)

        if not q:
            q = Quota(limit_seconds=1800)
            db[user.id] = q

        if q.remaining < seconds:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Quota exceeded",
            )

        q.used_seconds += seconds
        db[user.id] = q
        _save(db)
