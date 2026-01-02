# app/processing/mock_processor.py

from datetime import datetime
from app.state.jobs_store import JOBS


def process_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return

    # Simulate processing lifecycle
    from app.state.state_manager import transition_state
    transition_state(job, "processing")

    job["updated_at"] = datetime.utcnow()

    # Immediately complete (mock)
    job["status"] = "completed"
    job["completed_at"] = datetime.utcnow()
