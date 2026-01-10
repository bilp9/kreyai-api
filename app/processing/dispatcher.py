import threading
import asyncio
from app.processing.runner import run_job

def dispatch_job(job_id: str):
    def _run():
        asyncio.run(run_job(job_id))

    threading.Thread(target=_run, daemon=True).start()
