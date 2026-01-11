# app/processing/dispatcher.py
from app.constants import JobStatus
from app.events.recorder import record_event
from app.queueing import get_queue
from app.state.jobs_store import JOBS
from app.state.state_manager import transition_job


def dispatch_job(job_id: str) -> None:
    job = JOBS.get(job_id)
    if not job:
        return

    # Ensure correct state: UPLOADED -> QUEUED
    transition_job(job, JobStatus.QUEUED)
    record_event(job, "queued", "Job queued (durable local queue)")

    q = get_queue()
    q.enqueue(job_id)
