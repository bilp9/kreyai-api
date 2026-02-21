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
from app.services.email_service import send_completion_email

db = firestore.Client()
JOBS_COL = "jobs"


# -------------------------
# Subtitle helpers
# -------------------------

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
        content += f"{start} --> {end}\n{str(seg['text']).strip()}\n\n"
    return content


def build_srt_content(segments: List[Dict[str, Any]]) -> str:
    content = ""
    for i, seg in enumerate(segments, start=1):
        start = seconds_to_timestamp_srt(float(seg["start"]))
        end = seconds_to_timestamp_srt(float(seg["end"]))
        content += f"{i}\n{start} --> {end}\n{str(seg['text']).strip()}\n\n"
    return content


def build_docx_bytes(transcript_text: str) -> bytes:
    doc = Document()
    for line in transcript_text.split("\n"):
        doc.add_paragraph(line)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


# -------------------------
# Firestore helpers
# -------------------------

def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    snap = db.collection(JOBS_COL).document(job_id).get()
    return snap.to_dict() if snap.exists else None


def update_job(job_id: str, data: Dict[str, Any]) -> None:
    payload = dict(data)
    payload["updated_at"] = datetime.utcnow().isoformat()
    db.collection(JOBS_COL).document(job_id).update(payload)


def claim_one_queued_job() -> Optional[str]:
    jobs_ref = db.collection(JOBS_COL)

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
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )
            return True

        txn = db.transaction()
        if _txn_claim(txn):
            print(f"✅ Claimed job {job_id}")
            return job_id

    return None


# -------------------------
# Job runner
# -------------------------

async def run_job(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return

    attempts = int(job.get("attempts", 0)) + 1
    update_job(
        job_id,
        {
            "attempts": attempts,
            "progress": 5,
            "status": JobStatus.PROCESSING.value,
        },
    )

    record_event(
        job_id,
        "processing",
        f"Attempt {attempts}",
        JobStatus.PROCESSING.value,
    )

    storage = get_storage()

    try:
        upload_uri = job.get("upload_path")
        if not upload_uri:
            raise RuntimeError("Missing upload_path on job")

        safe_filename = os.path.basename(upload_uri)
        local_path = f"/tmp/{job_id}_{safe_filename}"

        print(f"⬇️ Downloading {upload_uri} to {local_path}")

        storage.download_to_file(source=upload_uri, local_path=local_path)

        last_progress = {"pct": -1}

        def progress_cb(pct: int, msg: str):
            pct = int(pct)
            if pct - last_progress["pct"] >= 5:
                last_progress["pct"] = pct
                update_job(job_id, {"progress": pct})
                record_event(
                    job_id,
                    "progress",
                    msg,
                    JobStatus.PROCESSING.value,
                )

        result = await asyncio.wait_for(
            asyncio.to_thread(
                transcribe_audio,
                local_path,
                progress_cb=progress_cb,
            ),
            timeout=PROCESS_ATTEMPT_TIMEOUT_SECONDS,
        )

        transcript_text = result["text"]
        segments = result.get("segments", []) or []

        storage.save_output(
            job_id,
            "transcript.txt",
            transcript_text.encode("utf-8"),
            content_type="text/plain",
        )

        if segments:
            vtt = build_vtt_content(segments)
            srt = build_srt_content(segments)

            storage.save_output(
                job_id,
                "transcript.vtt",
                vtt.encode("utf-8"),
                content_type="text/vtt",
            )

            storage.save_output(
                job_id,
                "transcript.srt",
                srt.encode("utf-8"),
                content_type="text/plain",
            )

        docx_bytes = build_docx_bytes(transcript_text)
        storage.save_output(
            job_id,
            "transcript.docx",
            docx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        update_job(
            job_id,
            {
                "status": JobStatus.COMPLETED.value,
                "progress": 100,
                "completed_at": datetime.utcnow().isoformat(),
                "artifacts": {
                    "txt": "transcript.txt",
                    "vtt": "transcript.vtt",
                    "srt": "transcript.srt",
                    "docx": "transcript.docx",
                },
            },
        )

        record_event(
            job_id,
            "completed",
            "Transcription completed",
            JobStatus.COMPLETED.value,
        )

        # 🔥 Non-blocking completion email
        try:
            asyncio.create_task(
                send_completion_email(job["email"], job_id)
            )
        except Exception as email_err:
            print(f"⚠️ Email scheduling failed: {email_err}")

        if os.path.exists(local_path):
            os.remove(local_path)

    except Exception as e:
        err = str(e)
        print(f"🔥 Worker error: {err}")

        record_event(job_id, "error", err, JobStatus.FAILED.value)

        if attempts < PROCESS_MAX_ATTEMPTS:
            update_job(job_id, {"status": JobStatus.QUEUED.value})
            record_event(
                job_id,
                "requeued",
                "Retrying job",
                JobStatus.QUEUED.value,
            )
        else:
            update_job(job_id, {"status": JobStatus.FAILED.value})
            record_event(
                job_id,
                "failed",
                "Max attempts reached",
                JobStatus.FAILED.value,
            )


def process_next_job(worker_id: str) -> bool:
    print(f"🚀 Worker {worker_id} checking queue...")
    job_id = claim_one_queued_job()

    if not job_id:
        return False

    asyncio.run(run_job(job_id))
    print("✅ Worker finished.")
    return True