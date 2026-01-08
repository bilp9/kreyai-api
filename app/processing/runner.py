# app/processing/runner.py
import asyncio
import time

from app.state.jobs_store import JOBS
from app.constants import (
    JobStatus,
    MAX_JOB_ATTEMPTS,
    JOB_ATTEMPT_TIMEOUT_SECONDS,
    PROGRESS_INCREMENT,
    PROGRESS_STEP_SECONDS,
)
from app.events.recorder import record_event


async def run_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return

    if job["attempts"] >= MAX_JOB_ATTEMPTS:
        job["status"] = JobStatus.FAILED
        record_event(job, "failed", "Max retry attempts reached")
        return

    job["attempts"] += 1
    job["status"] = JobStatus.PROCESSING
    job["progress"] = 0

    record_event(job, "processing_started", f"Attempt {job['attempts']}")

    start_time = time.time()

    try:
        while job["progress"] < 100:
            await asyncio.sleep(PROGRESS_STEP_SECONDS)

            # timeout enforcement
            if time.time() - start_time > JOB_ATTEMPT_TIMEOUT_SECONDS:
                raise TimeoutError("Job processing timeout")

            job["progress"] += PROGRESS_INCREMENT
            job["progress"] = min(job["progress"], 100)

            record_event(
                job,
                "progress",
                f"{job['progress']}%",
            )

        job["status"] = JobStatus.COMPLETED
        record_event(job, "completed", "Job completed successfully")

    except Exception as e:
        record_event(job, "error", str(e))

        if job["attempts"] < MAX_JOB_ATTEMPTS:
            record_event(job, "retrying", "Retrying job")
            await run_job(job_id)
        else:
            job["status"] = JobStatus.FAILED
            record_event(job, "failed", "Job permanently failed")
