import queue

# Thread-safe, in-memory queue (Phase-2B)
job_queue: queue.Queue[str] = queue.Queue()


def enqueue_job(job_id: str):
    job_queue.put(job_id)


def dequeue_job() -> str:
    return job_queue.get()
