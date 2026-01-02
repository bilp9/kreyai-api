import time
from app.constants import (
    JobStatus,
    MAX_JOB_ATTEMPTS,
    JOB_ATTEMPT_TIMEOUT_SECONDS,
)
from app.events.recorder import record_event

def run_job(job: dict):
    start = time.time()
    job["attempts"] += 1

    record_event(
        job,
        "attempt_started",
        f"Attempt {job['attempts']}",
    )

    try:
        # Simulated processing loop
        for pct in range(0, 101, 10):
            if time.time() - start > JOB_ATTEMPT_TIMEOUT_SECONDS:
                raise TimeoutError("Processing timed out")

            job["progress"] = pct
            time.sleep(0.3)

        job["status"] = JobStatus.COMPLETED
        record_event(job, "completed", "Job completed successfully")

    except Exception as e:
        record_event(job, "error", str(e))

        if job["attempts"] >= MAX_JOB_ATTEMPTS:
            job["status"] = JobStatus.FAILED
            record_event(job, "failed", "Max retries reached")
        else:
            job["status"] = JobStatus.QUEUED
            record_event(job, "retry", "Retrying job")
            run_job(job)
