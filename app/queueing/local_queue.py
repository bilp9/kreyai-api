# app/queueing/local_queue.py
from queue import Queue, Empty
from typing import Dict, Any, Optional
import uuid

from app.queueing.base import QueueClient


_LOCAL_Q: Queue = Queue()


class LocalQueueClient(QueueClient):
    def enqueue(self, payload: Dict[str, Any]) -> str:
        task_id = f"local-{uuid.uuid4().hex[:10]}"
        payload = dict(payload)
        payload["_task_id"] = task_id
        _LOCAL_Q.put(payload)
        return task_id

    def dequeue(self, timeout_seconds: int = 1) -> Optional[Dict[str, Any]]:
        try:
            return _LOCAL_Q.get(timeout=timeout_seconds)
        except Empty:
            return None
