# app/processing/runner.py

import time
import random
from app.constants import JobStatus
from app.events.recorder import record_event


def run_job(job: dict):
    """
    Simulated processing runner.
    Phase-2 groundwork: progress, failure, completion.
    """

    try:
        for step in range(1, 6):
            time.sleep(1)

            job["progress"] = step * 20
            record_event(job, "progress", f"{job['progress']}% complete")

        # Simulate random failure
        if random.random() < 0.1:
            raise RuntimeError("Simulated processing failure")

        job["status"] = JobStatus.COMPLETED
        record_event(job, "completed", "Job completed successfully")

    except Exception as e:
        job["status"] = JobStatus.FAILED
        record_event(job, "failed", str(e))
