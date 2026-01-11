# app/processing/runner.py
from __future__ import annotations

import asyncio
import time
from typing import Optional

from app.constants import (
    JobStatus,
    PROCESS_ATTEMPT_TIMEOUT_SECONDS,
    PROCESS_MAX_ATTEMPTS,
)
from app.events.recorder import record_event
from app.queueing import get_queue
from app.state.jobs_store import JOBS
from app.state.state_manager import transition_job


async def _simulate_processing(job: dict) -> None:
    steps = 10
    for _ in range(steps):
        await asyncio.sleep(0.5)
        job["progress"] = min(100, job.get("progress", 0) + 10)
        record_event(job, "progress", f"{job['progress']}%")
        if job["progress"] >= 100:
            break


async def run_job(job_id: str) -> None:
    job = JOBS.get(job_id)
    if not job:
        return

    q = get_queue()

    if job["status"] != JobStatus.QUEUED:
        return

    job["attempts"] += 1
    transition_job(job, JobStatus.PROCESSING)
    record_event(job, "processing", f"Attempt {job['attempts']}")

    try:
        await asyncio.wait_for(
            _simulate_processing(job),
            timeout=PROCESS_ATTEMPT_TIMEOUT_SECONDS,
        )

        job["progress"] = 100
        transition_job(job, JobStatus.COMPLETED)
        record_event(job, "completed", "Job completed")
        q.complete(job_id)

    except Exception as e:
        record_event(job, "error", str(e))

        if job["attempts"] < PROCESS_MAX_ATTEMPTS:
            transition_job(job, JobStatus.QUEUED)
            q.enqueue(job_id)
        else:
            transition_job(job, JobStatus.FAILED)
            q.fail(job_id, str(e))


def process_next_job(worker_id: str) -> bool:
    """
    Called by worker process.
    Returns True if work was done, False if idle.
    """
    q = get_queue()
    job_id: Optional[str] = q.dequeue()

    if not job_id:
        return False

    asyncio.run(run_job(job_id))
    return True
