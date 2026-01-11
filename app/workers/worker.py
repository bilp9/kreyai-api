# app/workers/worker.py
import time
import uuid

from app.processing.runner import process_next_job

WORKER_ID = f"worker-{uuid.uuid4().hex[:6]}"


def worker_loop():
    print(f"🟢 Worker {WORKER_ID} started")

    while True:
        try:
            did_work = process_next_job(WORKER_ID)

            if not did_work:
                time.sleep(1)

        except KeyboardInterrupt:
            print(f"🛑 Worker {WORKER_ID} stopping")
            break

        except Exception as e:
            print(f"🔥 Worker error: {e}")
            time.sleep(2)


if __name__ == "__main__":
    worker_loop()
