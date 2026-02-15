# app/processing/runner.py

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List

from google.cloud import firestore
from docx import Document
from io import BytesIO

from app.constants import (
    JobStatus,
    PROCESS_ATTEMPT_TIMEOUT_SECONDS,
    PROCESS_MAX_ATTEMPTS,
)
from app.transcription.engine import transcribe_audio
from app.storage.backend import get_storage
from app.events.recorder import record_event

db = firestore.Client()
JOBS_COL = "jobs"


# -------------------------------------------------------
# Subtitle helpers
# -------------------------------------------------------

def seconds_to_timestamp_vtt(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02}:{minutes:02}:{secs:06.3f}"


def seconds_to_timestamp_srt(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def build_vtt_content(segments: List[Dict[str, Any]]) -> str:
    content = "WEBVTT\n\n"
    for seg in segments:
        start = seconds_to_timestamp_vtt(float(seg["start"]))
        end = seconds_to_timestamp_vtt(float(seg["end"]))
        content += f"{start} --> {end}\n"
        content += str(seg["text"]).strip() + "\n\n"
    return content


def build_srt_content(segments: List[Dict[str, Any]]) -> str:
    content = ""
    for i, seg in enumerate(segments, start=1):
        start = seconds_to_timestamp_srt(float(seg["start"]))
        end = seconds_to_timestamp_srt(float(seg["end"]))
        content += f"{i}\n"
        content += f"{start} --> {end}\n"
        content += str(seg["text"]).strip() + "\n\n"
    return content


def build_docx_bytes(transcript_text: str) -> bytes:
    doc = Document()
    # Split on newlines; keep empty lines as paragraph breaks
    for line in transcript_text.split("\n"):
        doc.add_paragraph(line)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


# -------------------------------------------------------
# Firestore helpers
# -------------------------------------------------------

def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    doc = db.collection(JOBS_COL).document(job_id).get()
    if not doc.exists:
        return None
    return doc.to_dict()


def update_job(job_id: str, data: Dict[str, Any]) -> None:
    data = dict(data)
    data["updated_at"] = datetime.utcnow().isoformat()
    db.collection(JOBS_COL).document(job_id).update(data)


def claim_one_queued_job() -> Optional[str]:
    """
    Claims ONE job with status=queued by flipping it to processing.
    Uses a transaction + status precondition check.
    """
    jobs_ref = db.collection(JOBS_COL)

    # Pick oldest queued (if you store created_at)
    # If you don’t have created_at indexed, keep it simple.
    query = jobs_ref.where("status", "==", JobStatus.QUEUED).limit(5).stream()

    candidates = [doc for doc in query]
    if not candidates:
        return None

    # Try to claim one safely
    for doc in candidates:
        job_id = doc.id
        doc_ref = jobs_ref.document(job_id)

        @firestore.transactional
        def _txn_claim(transaction: firestore.Transaction) -> bool:
            snap = doc_ref.get(transaction=transaction)
            if not snap.exists:
                return False
            cur = snap.to_dict() or {}
            if cur.get("status") != JobStatus.QUEUED:
                return False

            transaction.update(doc_ref, {
                "status": JobStatus.PROCESSING,
                "updated_at": datetime.utcnow().isoformat(),
            })
            return True

        txn = db.transaction()
        claimed = _txn_claim(txn)
        if claimed:
            return job_id

    return None


# -------------------------------------------------------
# Job runner
# -------------------------------------------------------

async def run_job(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return

    attempts = int(job.get("attempts", 0)) + 1

    update_job(job_id, {
        "attempts": attempts,
        "progress": 5,
        "status": JobStatus.PROCESSING,
    })

    record_event(job_id, "processing", f"Attempt {attempts}", JobStatus.PROCESSING)

    storage = get_storage()

    try:
        upload_path = job.get("upload_path")
        if not upload_path:
            raise RuntimeError("Missing upload_path on job")

        def progress_cb(pct: int, msg: str):
            # Keep it light: do not write too frequently if your model updates often
            update_job(job_id, {"progress": int(pct)})
            record_event(job_id, "progress", msg, JobStatus.PROCESSING)

        # Must return: {"text": str, "segments": [{start,end,text,(optional speaker)}]}
        result = await asyncio.wait_for(
            asyncio.to_thread(transcribe_audio, upload_path, progress_cb),
            timeout=PROCESS_ATTEMPT_TIMEOUT_SECONDS,
        )

        transcript_text = result["text"]
        segments = result.get("segments", []) or []

        # ---- Save outputs
        storage.save_output(job_id, "transcript.txt", transcript_text.encode("utf-8"))

        if segments:
            vtt = build_vtt_content(segments)
            srt = build_srt_content(segments)
            storage.save_output(job_id, "transcript.vtt", vtt.encode("utf-8"))
            storage.save_output(job_id, "transcript.srt", srt.encode("utf-8"))

        docx_bytes = build_docx_bytes(transcript_text)
        storage.save_output(job_id, "transcript.docx", docx_bytes)

        update_job(job_id, {
            "status": JobStatus.COMPLETED,
            "progress": 100,
            "completed_at": datetime.utcnow().isoformat(),
            "artifacts": {
                "txt": "transcript.txt",
                "vtt": "transcript.vtt",
                "srt": "transcript.srt",
                "docx": "transcript.docx",
            },
        })

        record_event(job_id, "completed", "Transcription completed", JobStatus.COMPLETED)

    except Exception as e:
        err = str(e)
        record_event(job_id, "error", err, JobStatus.FAILED)

        if attempts < PROCESS_MAX_ATTEMPTS:
            update_job(job_id, {"status": JobStatus.QUEUED})
            record_event(job_id, "requeued", "Retrying job", JobStatus.QUEUED)
        else:
            update_job(job_id, {"status": JobStatus.FAILED})
            record_event(job_id, "failed", "Max attempts reached", JobStatus.FAILED)


def process_next_job(worker_id: str) -> bool:
    job_id = claim_one_queued_job()
    if not job_id:
        return False

    asyncio.run(run_job(job_id))
    return True
