# app/state/state_manager.py
from datetime import datetime
from app.constants import JobStatus

ALLOWED_TRANSITIONS = {
    JobStatus.QUEUED: {JobStatus.PROCESSING},
    JobStatus.PROCESSING: {JobStatus.COMPLETED, JobStatus.FAILED},
    JobStatus.FAILED: {JobStatus.PROCESSING, JobStatus.EXPIRED},
}

def transition(job, new_status, reason=None):
    current = job["status"]

    if current not in ALLOWED_TRANSITIONS:
        return

    if new_status not in ALLOWED_TRANSITIONS[current]:
        return

    job["status"] = new_status
    job["updated_at"] = datetime.utcnow().isoformat()

    if reason:
        job["last_error"] = reason

def update_progress(job, percent: int):
    job["progress"] = percent
