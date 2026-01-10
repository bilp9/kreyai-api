# app/state/state_manager.py

from app.constants import JobStatus
from app.state.job_transitions import ALLOWED_TRANSITIONS


def can_transition(from_status: JobStatus, to_status: JobStatus) -> bool:
    """
    Check whether a job is allowed to move from one state to another.
    """
    return to_status in ALLOWED_TRANSITIONS.get(from_status, set())


def transition_job(job: dict, new_status: JobStatus):
    """
    Transition a job to a new status if allowed by the lifecycle rules.
    """
    current = job["status"]

    if not can_transition(current, new_status):
        raise RuntimeError(
            f"Invalid job transition: {current} → {new_status}"
        )

    job["status"] = new_status
