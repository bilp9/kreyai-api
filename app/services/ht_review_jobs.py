from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore

from app.events.recorder import record_event
from app.services.ht_llm_review import run_ht_llm_review
from app.state.firestore_jobs import COLLECTION as JOBS_COLLECTION
from app.state.firestore_jobs import db
from app.state.firestore_jobs import update_job as fs_update_job
from app.storage.backend import get_storage


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_ht_review_job(
    job_id: str,
    *,
    model: str | None = None,
    prompt: str | None = None,
    glossary_terms: list[str] | None = None,
) -> dict[str, Any]:
    doc_ref = db.collection(JOBS_COLLECTION).document(job_id)

    @firestore.transactional
    def _claim(transaction: firestore.Transaction) -> tuple[dict[str, Any], bool]:
        snap = doc_ref.get(transaction=transaction)
        if not snap.exists:
            raise RuntimeError("Job not found.")

        job_data = snap.to_dict() or {}
        status = str(job_data.get("ht_review_status") or "").strip().lower()
        if status == "running":
            return job_data, False

        transaction.update(
            doc_ref,
            {
                "ht_review_status": "running",
                "ht_review_error": None,
                "ht_review_requested_at": _utcnow_iso(),
                "ht_review_glossary_terms": glossary_terms or [],
                "updated_at": _utcnow_iso(),
            },
        )
        return job_data, True

    job, queued = _claim(db.transaction())

    if not queued:
        return {
            "job_id": job_id,
            "queued": False,
            "already_running": True,
            "status": "running",
            "model": job.get("ht_review_model"),
        }

    record_event(job_id, "ht_review_started", "Optional HT LLM cleanup started", str(job.get("status") or ""))

    return {
        "job_id": job_id,
        "queued": True,
        "already_running": False,
        "status": "running",
        "model": model,
        "prompt": prompt,
        "glossary_terms": glossary_terms or [],
    }


def run_ht_review_job(
    job_id: str,
    *,
    model: str | None = None,
    prompt: str | None = None,
    glossary_terms: list[str] | None = None,
) -> None:
    storage = get_storage()

    try:
        if not storage.output_exists(job_id, "transcript.txt"):
            raise RuntimeError("Raw transcript output is not available yet.")

        raw_text = storage.read_output_text(job_id, "transcript.txt")
        review = run_ht_llm_review(
            raw_text,
            model=model,
            prompt=prompt,
            glossary_terms=glossary_terms,
        )
        corrected_text = str(review.get("corrected_text") or "").strip()

        storage.save_output(
            job_id,
            "transcript.llm-corrected.txt",
            (corrected_text + "\n").encode("utf-8"),
            "text/plain; charset=utf-8",
        )
        storage.save_output(
            job_id,
            "transcript.llm-review.json",
            (json.dumps(review, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            "application/json; charset=utf-8",
        )

        fs_update_job(
            job_id,
            {
                "ht_review_status": "completed",
                "ht_review_error": None,
                "ht_review_updated_at": _utcnow_iso(),
                "ht_review_model": review.get("model"),
                "ht_review_glossary_terms": review.get("glossary_terms") or [],
            },
        )
        record_event(job_id, "ht_review_completed", "Optional HT LLM cleanup completed", "completed")
    except Exception as exc:
        fs_update_job(
            job_id,
            {
                "ht_review_status": "failed",
                "ht_review_error": str(exc),
            },
        )
        record_event(job_id, "ht_review_failed", f"Optional HT LLM cleanup failed: {exc}", "failed")
        raise
