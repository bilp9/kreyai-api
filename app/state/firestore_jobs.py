from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from google.cloud import firestore

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


def _sort_key(job: Dict[str, Any]) -> str:
    return str(job.get("created_at") or job.get("updated_at") or "")


def _normalized_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _job_matches(
    job: Dict[str, Any],
    *,
    status: Optional[str] = None,
    language: Optional[str] = None,
    email_query: Optional[str] = None,
) -> bool:
    if status and _normalized_text(job.get("status")) != _normalized_text(status):
        return False

    if language and _normalized_text(job.get("language")) != _normalized_text(language):
        return False

    if email_query and email_query not in _normalized_text(job.get("email")):
        return False

    return True


def list_recent_jobs(
    limit: int = 25,
    *,
    status: Optional[str] = None,
    language: Optional[str] = None,
    email_query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    jobs: List[Dict[str, Any]] = []
    normalized_email_query = _normalized_text(email_query)
    normalized_status = _normalized_text(status)
    normalized_language = _normalized_text(language)
    batch_size = max(limit * 4, 100) if normalized_email_query else limit
    max_scanned = max(limit * 20, 500)

    try:
        query = db.collection(COLLECTION)

        if normalized_status:
            query = query.where("status", "==", normalized_status)

        if normalized_language:
            query = query.where("language", "==", normalized_language)

        query = query.order_by("created_at", direction=firestore.Query.DESCENDING)

        scanned = 0
        last_doc = None

        while len(jobs) < limit and scanned < max_scanned:
            page_query = query.limit(batch_size)
            if last_doc is not None:
                page_query = page_query.start_after(last_doc)

            docs = list(page_query.stream())
            if not docs:
                break

            for doc in docs:
                scanned += 1
                data = doc.to_dict() or {}
                job = {"job_id": doc.id, **data}
                if _job_matches(
                    job,
                    status=normalized_status,
                    language=normalized_language,
                    email_query=normalized_email_query,
                ):
                    jobs.append(job)
                    if len(jobs) >= limit:
                        break

            last_doc = docs[-1]
    except Exception:
        fetch_limit = max(limit * 8, 100) if (normalized_status or normalized_language or normalized_email_query) else limit
        docs = db.collection(COLLECTION).limit(fetch_limit).stream()

        for doc in docs:
            data = doc.to_dict() or {}
            job = {"job_id": doc.id, **data}
            if _job_matches(
                job,
                status=normalized_status,
                language=normalized_language,
                email_query=normalized_email_query,
            ):
                jobs.append(job)

    jobs.sort(key=_sort_key, reverse=True)
    return jobs[:limit]


def count_jobs_by_status(status: str) -> int:
    try:
        query = db.collection(COLLECTION).where("status", "==", status).count()
        result = query.get()
        if not result:
            return 0
        return int(result[0][0].value)
    except Exception:
        docs = db.collection(COLLECTION).where("status", "==", status).stream()
        return sum(1 for _ in docs)


def count_jobs_by_field(field_name: str, value: str) -> int:
    try:
        query = db.collection(COLLECTION).where(field_name, "==", value).count()
        result = query.get()
        if not result:
            return 0
        return int(result[0][0].value)
    except Exception:
        docs = db.collection(COLLECTION).where(field_name, "==", value).stream()
        return sum(1 for _ in docs)


def update_job(job_id: str, updates: Dict[str, Any]) -> None:
    updates["updated_at"] = datetime.utcnow().isoformat()
    db.collection(COLLECTION).document(job_id).update(updates)
