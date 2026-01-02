# app/state/state_manager.py

from app.state.job_transitions import ALLOWED_TRANSITIONS

def transition_state(job: dict, new_state: str):
    current = job.get("status")

    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if new_state not in allowed:
        raise ValueError(
            f"Invalid state transition: {current} → {new_state}"
        )

    job["status"] = new_state
