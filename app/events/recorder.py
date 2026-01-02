# app/events/recorder.py

from datetime import datetime
from typing import Dict, List


def record_event(job: Dict, event_type: str, message: str):
    """
    Append an immutable event to a job's event log.
    """

    event = {
        "timestamp": datetime.utcnow().isoformat(),
        "type": event_type,
        "message": message,
        "status": job.get("status"),
    }

    job.setdefault("events", []).append(event)


def get_events(job: Dict) -> List[Dict]:
    """
    Read-only accessor for job events.
    """
    return job.get("events", [])
