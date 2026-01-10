# app/processing/dispatcher.py
from app.queueing.memory_queue import get_queue
from app.state.jobs_store import JOBS
from app.events.recorder import record_event

def dispatch_job(job_id: str) -> None:
    """
    Phase-2B: dispatch == enqueue.
    No threads, no asyncio.run, no create_task here.
    """
    job = JOBS.get(job_id)
    if not job:
        return

    q = get_queue()
    q.put_nowait(job_id)
    record_event(job, "enqueued", "Job enqueued for processing")
