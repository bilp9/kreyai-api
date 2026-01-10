# app/processing/runner.py
import asyncio
import random
from datetime import datetime

from app.constants import JobStatus
from app.state.jobs_store import JOBS
from app.state.state_manager import transition_job
from app.events.recorder import record_event


async def run_job(job_id: str) -> None:
    """
    Phase-2B: Simulated processing.
    - transitions to PROCESSING
    - updates progress 0..100
    - ends COMPLETED (or FAILED if simulated error)
    """
    job = JOBS.get(job_id)
    if not job:
        return

    # Guard: only start processing from QUEUED (or UPLOADED if you're allowing that)
    try:
        transition_job(job, JobStatus.PROCESSING)
    except Exception:
        # If your transition rules are strict, make sure upload sets QUEUED before dispatch.
        record_event(job, "runner_skipped", f"Not runnable from status={job.get('status')}")
        return

    record_event(job, "processing", "Job processing started")

    # Optional: simulate occasional failures (keep low for now)
    fail_rate = float(job.get("simulate_fail_rate", 0.0))  # e.g. 0.15
    should_fail = random.random() < fail_rate

    # Simulate work in 10 steps
    for step in range(1, 11):
        await asyncio.sleep(0.4)
        job["progress"] = step * 10
        record_event(job, "progress", f"{job['progress']}%")

        if should_fail and step == 6:
            transition_job(job, JobStatus.FAILED)
            record_event(job, "failed", "Simulated processing failure")
            return

    transition_job(job, JobStatus.COMPLETED)
    job["completed_at"] = datetime.utcnow().isoformat()
    record_event(job, "completed", "Job completed successfully")
