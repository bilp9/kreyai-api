# app/processing/worker.py
from app.queueing.memory_queue import get_queue
from app.processing.runner import run_job

async def worker_loop():
    """
    One long-running async loop owned by FastAPI's event loop.
    Pulls job_ids from the queue and executes run_job(job_id).
    """
    queue = get_queue()

    while True:
        job_id = await queue.get()
        try:
            await run_job(job_id)
        except Exception as e:
            # runner.py should already record a FAILED event/status;
            # this is a last-resort safety net.
            print(f"[WORKER ERROR] job_id={job_id} err={e}")
        finally:
            queue.task_done()
