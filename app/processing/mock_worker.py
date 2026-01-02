# app/processing/mock_worker.py

import time
import random
from datetime import datetime
from typing import Dict

from app.constants import (
    JobStatus,
    MAX_PROCESSING_SECONDS,
    PROGRESS_STEP_SECONDS,
)


def process_job(job: Dict):
    """
    Mock background processor with:
    - progress updates
    - timeout handling
    - simulated failures
    """

    start_time = time.time()
    job["status"] = JobStatus.PROCESSING
    job["progress"] = 0
    job["updated_at"] = datetime.utcnow().isoformat()

    try:
        while job["progress"] < 100:
            elapsed = time.time() - start_time

            # Timeout guard
            if elapsed > MAX_PROCESSING_SECONDS:
                raise TimeoutError("Processing timeout exceeded")

            time.sleep(PROGRESS_STEP_SECONDS)

            # Simulate progress
            job["progress"] += random.randint(10, 20)
            job["progress"] = min(job["progress"], 100)
            job["updated_at"] = datetime.utcnow().isoformat()

            # 🔥 Failure simulation (20% chance)
            if random.random() < 0.2:
                raise RuntimeError("Simulated processing failure")

        # Success
        job["status"] = JobStatus.COMPLETED
        job["result"] = {
            "message": "Mock transcription completed",
            "format": "txt",
        }

    except Exception as e:
        job["status"] = JobStatus.FAILED
        job["error"] = str(e)

    finally:
        job["updated_at"] = datetime.utcnow().isoformat()
