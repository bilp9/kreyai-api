# app/processing/dispatcher.py

from app.constants import JobStatus
from app.processing.runner import run_job
from app.events.recorder import record_event


def dispatch_job(job: dict):
    """
    Dispatch a verified & uploaded job into processing.

    This function is synchronous in Phase-2 groundwork.
    It will later enqueue async workers.
    """

    # Guard
    if job["status"] not in {JobStatus.UPLOADED, JobStatus.QUEUED}:
        raise ValueError("Job not ready for dispatch")

    job["status"] = JobStatus.PROCESSING
    record_event(job, "processing_started", "Job processing started")

    # Run (mock / sync for now)
    run_job(job)
