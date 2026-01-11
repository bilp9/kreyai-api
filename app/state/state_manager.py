# app/state/state_manager.py
from __future__ import annotations

from app.constants import JobStatus
from app.state.job_transitions import ALLOWED_TRANSITIONS


def can_transition(from_status: JobStatus, to_status: JobStatus) -> bool:
    return to_status in ALLOWED_TRANSITIONS.get(from_status, set())


def transition_job(job: dict, new_status: JobStatus) -> None:
    current = job["status"]
    allowed = ALLOWED_TRANSITIONS.get(current, set())

    if new_status not in allowed:
        raise RuntimeError(f"Invalid job transition: {current} → {new_status}")

    job["status"] = new_status
