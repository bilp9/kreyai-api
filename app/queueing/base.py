from abc import ABC, abstractmethod
from typing import Optional

class JobQueue(ABC):

    @abstractmethod
    def enqueue(self, job_id: str) -> None:
        ...

    @abstractmethod
    def lease(self) -> Optional[str]:
        """
        Return a job_id if available and lock it.
        Return None if no work is available.
        """
        ...

    @abstractmethod
    def complete(self, job_id: str) -> None:
        ...

    @abstractmethod
    def fail(self, job_id: str, reason: str) -> None:
        ...
