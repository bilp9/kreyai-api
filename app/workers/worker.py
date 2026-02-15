# app/workers/worker.py

import os
import asyncio

from app.processing.runner import run_job

def main():
    job_id = os.environ.get("JOB_ID")

    if not job_id:
        raise RuntimeError("JOB_ID not provided to worker")

    asyncio.run(run_job(job_id))

if __name__ == "__main__":
    main()
