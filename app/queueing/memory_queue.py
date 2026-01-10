# app/queueing/memory_queue.py
import asyncio

# Simple in-memory queue for Phase-2B.
# Later we can swap this for Redis/PubSub without changing routes.
_job_queue: asyncio.Queue[str] = asyncio.Queue()

def get_queue() -> asyncio.Queue[str]:
    return _job_queue
