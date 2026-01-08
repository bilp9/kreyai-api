# app/processing/dispatcher.py
import asyncio
import threading
from app.processing.runner import run_job

def dispatch_job(job_id: str):
    """
    Launch job execution in a background thread
    with its own event loop (safe with FastAPI).
    """

    def _run():
        asyncio.run(run_job(job_id))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
