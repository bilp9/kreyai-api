# app/workers/worker.py
from __future__ import annotations

import os
import time
from typing import Optional

from app.processing.runner import process_next_job


def worker_loop() -> None:
    """
    Cloud Run Job entrypoint:
    - claim+process jobs until none left
    - exit 0 (so the execution is "successful")
    """
    worker_id = os.getenv("WORKER_ID", "cloudrun-worker")
    poll_seconds = float(os.getenv("WORKER_POLL_SECONDS", "1.0"))

    print(f"🚀 Worker starting... id={worker_id}")

    processed_any = False

    while True:
        did_work = process_next_job(worker_id)

        if not did_work:
            if processed_any:
                print("🏁 Queue empty. Worker exiting.")
            else:
                print("⏭️ No queued jobs found. Worker exiting.")
            return

        processed_any = True
        time.sleep(poll_seconds)


if __name__ == "__main__":
    worker_loop()
