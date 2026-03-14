from __future__ import annotations

import subprocess
import asyncio
import os
from datetime import datetime
import time
from io import BytesIO
from typing import Optional, Dict, Any, List

from google.cloud import firestore
from google.cloud.firestore_v1 import FieldFilter
from docx import Document

from app.constants import (
    JobStatus,
    PROCESS_ATTEMPT_TIMEOUT_SECONDS,
    PROCESS_MAX_ATTEMPTS,
    MAX_AUDIO_DURATION_SECONDS,
)

from app.transcription.engine import transcribe_audio
from app.transcription.diarization import diarize_audio  # NEW
from app.storage.backend import get_storage
from app.events.recorder import record_event

try:
    from app.services.email_service import send_completion_email
except Exception:
    send_completion_email = None


db = firestore.Client()
JOBS_COL = "jobs"

# ---------------------------------------------------------
# Chunking config
# ---------------------------------------------------------
CHUNK_IF_LONGER_THAN_SECONDS = 600  # 10 minutes
CHUNK_SIZE_SECONDS = 300            # 5 minutes


# ---------------------------------------------------------
# Claim Job
# ---------------------------------------------------------
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
                    "progress": int(cur.get("progress") or 0),
                    "status_message": "Claimed by worker",
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )

            return True

        if _txn_claim(db.transaction()):
            print(f"Claimed job {job_id}")
            return job_id

    return None


# ---------------------------------------------------------
# Time Formatting
# ---------------------------------------------------------
def _format_srt_time(seconds: float) -> str:

    ms = int((seconds - int(seconds)) * 1000)
    total = int(seconds)

    hh = total // 3600
    mm = (total % 3600) // 60
    ss = total % 60

    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def _format_vtt_time(seconds: float) -> str:

    ms = int((seconds - int(seconds)) * 1000)
    total = int(seconds)

    hh = total // 3600
    mm = (total % 3600) // 60
    ss = total % 60

    return f"{hh:02d}:{mm:02d}:{ss:02d}.{ms:03d}"


def _format_hhmmss(seconds: float) -> str:

    total = int(seconds)

    hh = total // 3600
    mm = (total % 3600) // 60
    ss = total % 60

    return f"{hh:02d}:{mm:02d}:{ss:02d}"


# ---------------------------------------------------------
# Segment Helpers
# ---------------------------------------------------------
def _segments_from_result(result: Dict[str, Any]) -> List[Dict[str, Any]]:

    segs = result.get("segments")

    if isinstance(segs, list):
        return [s for s in segs if isinstance(s, dict)]

    return []


# ---------------------------------------------------------
# Audio Helpers
# ---------------------------------------------------------
def get_audio_duration_seconds(file_path: str) -> float:

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    output = (result.stdout or "").strip()

    if not output:
        raise RuntimeError("Unable to determine audio duration via ffprobe")

    return float(output)


# ---------------------------------------------------------
# (All other functions unchanged)
# ---------------------------------------------------------

# ---------------------------------------------------------
# Run Job
# ---------------------------------------------------------
async def run_job(job_id: str):

    doc_ref = db.collection(JOBS_COL).document(job_id)
    snap = doc_ref.get()

    if not snap.exists:
        return

    job = snap.to_dict() or {}

    attempts = int(job.get("attempts") or 0)

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

        start_time = time.time()
        file_size_bytes = None
        audio_duration_seconds = None
        processing_time_seconds = None
        estimated_cost_usd = None
        realtime_factor = None

        storage = get_storage()

        source_blob = job.get("file_path") or job.get("upload_path")

        if not source_blob:
            raise RuntimeError("Job missing storage path")

        storage.download_to_file(source_blob, local_path)

        # ---------------------------------------------------------
        # NEW: Run speaker diarization before transcription
        # ---------------------------------------------------------
        try:
            print("Running speaker diarization...")
            speaker_segments = await asyncio.to_thread(
                diarize_audio,
                local_path
            )
            print(f"Diarization segments detected: {len(speaker_segments)}")
        except Exception as diarization_error:
            print("Diarization failed but continuing transcription:", diarization_error)
            speaker_segments = []

        # ---------------------------------------------------------

        if os.path.exists(local_path):
            file_size_bytes = os.path.getsize(local_path)

        duration = get_audio_duration_seconds(local_path)
        audio_duration_seconds = duration

        print(f"Audio duration: {duration} seconds")

        if duration > MAX_AUDIO_DURATION_SECONDS:
            raise RuntimeError(
                f"Audio exceeds maximum allowed duration ({MAX_AUDIO_DURATION_SECONDS} seconds)"
            )

        result = await asyncio.wait_for(
            transcribe_with_optional_chunking(
                local_path,
                language=job.get("language", "auto"),
            ),
            timeout=PROCESS_ATTEMPT_TIMEOUT_SECONDS,
        )

        save_outputs(storage, job_id, result)

        processing_time_seconds = round(time.time() - start_time, 3)
        estimated_cost_usd = estimate_cost_usd(audio_duration_seconds or 0.0)

        if audio_duration_seconds:
            realtime_factor = round(
                processing_time_seconds / audio_duration_seconds,
                4,
            )

        doc_ref.update(
            {
                "status": JobStatus.COMPLETED.value,
                "progress": 100,
                "status_message": "Completed",
                "completed_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "file_size_bytes": file_size_bytes,
                "audio_duration_seconds": audio_duration_seconds,
                "processing_time_seconds": processing_time_seconds,
                "estimated_cost_usd": estimated_cost_usd,
                "realtime_factor": realtime_factor,
                "model": "faster-whisper",
                "language_final": job.get("language", "auto"),
            }
        )

        if send_completion_email and job.get("email"):

            try:
                await send_completion_email(job["email"], job_id)
            except Exception as e:
                print("Email error", e)

    except Exception as e:

        failure_update = {
            "status": JobStatus.FAILED.value,
            "status_message": str(e),
            "updated_at": datetime.utcnow().isoformat(),
        }

        try:
            if os.path.exists(local_path) and file_size_bytes is None:
                file_size_bytes = os.path.getsize(local_path)
            if processing_time_seconds is None:
                processing_time_seconds = round(time.time() - start_time, 3)

            if audio_duration_seconds and processing_time_seconds:
                realtime_factor = round(
                    processing_time_seconds / audio_duration_seconds,
                    4,
                )

            if file_size_bytes is not None:
                failure_update["file_size_bytes"] = file_size_bytes
            if audio_duration_seconds is not None:
                failure_update["audio_duration_seconds"] = audio_duration_seconds
            if processing_time_seconds is not None:
                failure_update["processing_time_seconds"] = processing_time_seconds
            if realtime_factor is not None:
                failure_update["realtime_factor"] = realtime_factor
        except Exception:
            pass

        doc_ref.update(failure_update)

        record_event(job_id, "failed", str(e), JobStatus.FAILED.value)

    finally:

        if os.path.exists(local_path):
            os.remove(local_path)


# ---------------------------------------------------------
# Worker Entry
# ---------------------------------------------------------
def process_next_job(worker_id: str):

    print(f"Worker {worker_id} checking queue...")

    job_id = claim_one_queued_job()

    if not job_id:
        return False

    asyncio.run(run_job(job_id))

    print("Worker finished.")

    return True