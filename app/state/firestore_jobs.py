# app/state/firestore_jobs.py

from google.cloud import firestore
from typing import Optional, Dict, Any
from datetime import datetime

db = firestore.Client()
COLLECTION = "jobs"


def create_job(job: Dict[str, Any]) -> None:
    job["updated_at"] = datetime.utcnow().isoformat()
    db.collection(COLLECTION).document(job["job_id"]).set(job)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    doc = db.collection(COLLECTION).document(job_id).get()
    if not doc.exists:
        return None
    return doc.to_dict()


def update_job(job_id: str, updates: Dict[str, Any]) -> None:
    updates["updated_at"] = datetime.utcnow().isoformat()
    db.collection(COLLECTION).document(job_id).update(updates)
