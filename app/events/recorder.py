# app/events/recorder.py

from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from google.cloud import firestore

db = firestore.Client()


def record_event(job_id: str, event_type: str, message: str, status: str) -> None:
    """
    Append an immutable event to Firestore:
      jobs/{job_id}/events/{auto_id}
    """
    event = {
        "timestamp": datetime.utcnow().isoformat(),
        "type": event_type,
        "message": message,
        "status": status,
    }

    db.collection("jobs").document(job_id).collection("events").add(event)


def get_events(job_id: str, limit: int = 200) -> List[Dict]:
    """
    Returns newest-first (or change to oldest-first if you prefer).
    """
    events_ref = (
        db.collection("jobs")
        .document(job_id)
        .collection("events")
        .order_by("timestamp", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )

    return [doc.to_dict() for doc in events_ref.stream()]
