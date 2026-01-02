# app/queueing/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class QueueClient(ABC):
    @abstractmethod
    def enqueue(self, payload: Dict[str, Any]) -> str:
        """Returns a task_id / message_id."""
        raise NotImplementedError

    @abstractmethod
    def dequeue(self, timeout_seconds: int = 1) -> Optional[Dict[str, Any]]:
        """Returns payload or None if empty."""
        raise NotImplementedError
