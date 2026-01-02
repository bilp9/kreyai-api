# app/queueing/factory.py
import os
from app.queueing.base import QueueClient
from app.queueing.local_queue import LocalQueueClient

_QUEUE_SINGLETON: QueueClient | None = None


def get_queue_client() -> QueueClient:
    global _QUEUE_SINGLETON
    if _QUEUE_SINGLETON:
        return _QUEUE_SINGLETON

    backend = os.getenv("KREYAI_QUEUE_BACKEND", "local").lower()

    # Phase-2E: local only (for now)
    if backend == "local":
        _QUEUE_SINGLETON = LocalQueueClient()
        return _QUEUE_SINGLETON

    # Future: gcp_tasks, pubsub, etc.
    raise ValueError(f"Unsupported queue backend: {backend}")
