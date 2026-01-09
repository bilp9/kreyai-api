# app/state/state_manager.py
from app.state.job_transitions import ALLOWED_TRANSITIONS

def transition_job(job: dict, new_status):
    current = job["status"]

    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise RuntimeError(
            f"Invalid job transition: {current} → {new_status}"
        )

    job["status"] = new_status
