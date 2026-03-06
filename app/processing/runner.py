from __future__ import annotations

import asyncio
import os
from datetime import datetime
from io import BytesIO
from typing import Optional, Dict, Any, List

from google.cloud import firestore
from google.cloud.firestore_v1 import FieldFilter
from docx import Document

from app.constants import (
    JobStatus,
    PROCESS_ATTEMPT_TIMEOUT_SECONDS,
    PROCESS_MAX_ATTEMPTS,
)
from app.transcription.engine import transcribe_audio
from app.storage.backend import get_storage
from app.events.recorder import record_event

# Defensive import for email service
try:
    from app.services.email_service import send_completion_email
except Exception:
    send_completion_email = None


db = firestore.Client()
JOBS_COL = "jobs"


# ---------------------------------------------------------
# Claim Job
# ---------------------------------------------------------
def claim_one_queued_job() -> Optional[str]:
    jobs_ref = db.collection(JOBS_COL)

    # Prefer the newer FieldFilter form (removes the warning)
    candidates = list(
        jobs_ref.where(
            filter=FieldFilter("status", "==", JobStatus.QUEUED.value)
        ).limit(5).stream()
    )

    if not candidates:
        return None

    for doc in candidates:
        job_id = doc.id
        doc_ref = jobs_ref.document(job_id)

        @firestore.transactional
        def _txn_claim(txn: firestore.Transaction) -> bool:
            snap = doc_ref.get(transaction=txn)
            if not snap.exists:
                return False

            cur = snap.to_dict() or {}
            if cur.get("status") != JobStatus.QUEUED.value:
                return False

            txn.update(
                doc_ref,
                {
                    "status": JobStatus.PROCESSING.value,
                    "progress": int(cur.get("progress") or 0),
                    "status_message": "Claimed by worker",
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )
            return True

        if _txn_claim(db.transaction()):
            print(f"✅ Claimed job {job_id}")
            return job_id

    return None


# ---------------------------------------------------------
# Helpers: SRT/VTT (best-effort)
# ---------------------------------------------------------
def _format_srt_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    ms = int(round((seconds - int(seconds)) * 1000))
    total = int(seconds)
    hh = total // 3600
    mm = (total % 3600) // 60
    ss = total % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def _format_vtt_time(seconds: float) -> str:
    # WebVTT uses "." for milliseconds
    if seconds < 0:
        seconds = 0
    ms = int(round((seconds - int(seconds)) * 1000))
    total = int(seconds)
    hh = total // 3600
    mm = (total % 3600) // 60
    ss = total % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}.{ms:03d}"


def _segments_from_result(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    segs = result.get("segments")
    if isinstance(segs, list):
        return [s for s in segs if isinstance(s, dict)]
    return []


def _segments_to_srt(segments: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    idx = 1
    for s in segments:
        start = s.get("start")
        end = s.get("end")
        text = (s.get("text") or "").strip()
        if start is None or end is None or not text:
            continue
        lines.append(str(idx))
        lines.append(f"{_format_srt_time(float(start))} --> {_format_srt_time(float(end))}")
        lines.append(text)
        lines.append("")
        idx += 1
    return "\n".join(lines).strip() + "\n"


def _segments_to_vtt(segments: List[Dict[str, Any]]) -> str:
    lines: List[str] = ["WEBVTT", ""]
    for s in segments:
        start = s.get("start")
        end = s.get("end")
        text = (s.get("text") or "").strip()
        if start is None or end is None or not text:
            continue
        lines.append(f"{_format_vtt_time(float(start))} --> {_format_vtt_time(float(end))}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


# ---------------------------------------------------------
# Save Outputs
# ---------------------------------------------------------
def save_outputs(storage, job_id: str, result: Dict[str, Any]) -> None:
    text = (result.get("text") or "").strip()

    # TXT
    storage.save_output(
        job_id,
        "transcript.txt",
        (text + "\n").encode("utf-8"),
        "text/plain",
    )

    # DOCX
    doc = Document()
    for line in text.split("\n"):
        doc.add_paragraph(line)

    buf = BytesIO()
    doc.save(buf)

    storage.save_output(
        job_id,
        "transcript.docx",
        buf.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    # SRT/VTT (best effort)
    segments = _segments_from_result(result)
    if segments:
        srt = _segments_to_srt(segments)
        vtt = _segments_to_vtt(segments)

        storage.save_output(job_id, "transcript.srt", srt.encode("utf-8"), "application/x-subrip")
        storage.save_output(job_id, "transcript.vtt", vtt.encode("utf-8"), "text/vtt")


# ---------------------------------------------------------
# Run Job
# ---------------------------------------------------------
async def run_job(job_id: str) -> None:
    doc_ref = db.collection(JOBS_COL).document(job_id)
    snap = doc_ref.get()

    if not snap.exists:
        return

    job = snap.to_dict() or {}

    # ✅ SAFE INT CAST
    attempts_raw = job.get("attempts", 0)
    try:
        attempts = int(attempts_raw)
    except (ValueError, TypeError):
        attempts = 0

    if attempts >= PROCESS_MAX_ATTEMPTS:
        doc_ref.update(
            {
                "status": JobStatus.FAILED.value,
                "status_message": "Max attempts reached",
                "updated_at": datetime.utcnow().isoformat(),
            }
        )
        return

    doc_ref.update(
        {
            "attempts": attempts + 1,
            "status": JobStatus.PROCESSING.value,
            "status_message": "Starting",
            "updated_at": datetime.utcnow().isoformat(),
        }
    )

    local_path = f"/tmp/{job_id}_input"

    try:
        storage = get_storage()

        # Support both legacy and new field
        source_blob = job.get("file_path") or job.get("upload_path")
        if not source_blob:
            raise RuntimeError("Job missing storage path (file_path/upload_path)")

        # Download to disk
        doc_ref.update({"status_message": "Downloading upload", "progress": 2})
        storage.download_to_file(source_blob, local_path)

        def progress_cb(pct: int, msg: str):
            # Do NOT allow 100 here to become "done" before outputs are saved
            safe_pct = int(pct)
            if safe_pct >= 100:
                safe_pct = 95
            doc_ref.update(
                {
                    "progress": safe_pct,
                    "status_message": msg,
                    "updated_at": datetime.utcnow().isoformat(),
                }
            )

        # Run transcription
        result = await asyncio.wait_for(
            asyncio.to_thread(transcribe_audio, local_path, progress_cb=progress_cb, language=job.get("language"),
            ),
            timeout=PROCESS_ATTEMPT_TIMEOUT_SECONDS,
        )

        # Save outputs
        doc_ref.update({"status_message": "Saving outputs", "progress": 98})
        save_outputs(storage, job_id, result)

        # Mark completed (this is the source of truth)
        doc_ref.update(
            {
                "status": JobStatus.COMPLETED.value,
                "progress": 100,
                "status_message": "Completed",
                "completed_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }
        )

        # Email should NEVER flip a completed job to failed
        if send_completion_email and job.get("email"):
            try:
                await send_completion_email(job["email"], job_id)
            except Exception as e:
                print(f"⚠️ Completion email failed (non-fatal): {e}")
                record_event(job_id, "email_failed", str(e), JobStatus.COMPLETED.value)

    except Exception as e:
        print(f"🔥 Error: {e}")
        doc_ref.update(
            {
                "status": JobStatus.FAILED.value,
                "status_message": str(e),
                "updated_at": datetime.utcnow().isoformat(),
            }
        )
        record_event(job_id, "failed", str(e), JobStatus.FAILED.value)

    finally:
        if os.path.exists(local_path):
            os.remove(local_path)


# ---------------------------------------------------------
# Worker Entry
# ---------------------------------------------------------
def process_next_job(worker_id: str) -> bool:
    print(f"🚀 Worker {worker_id} checking queue...")
    job_id = claim_one_queued_job()
    if not job_id:
        return False

    asyncio.run(run_job(job_id))
    print("✅ Worker finished.")
    return True