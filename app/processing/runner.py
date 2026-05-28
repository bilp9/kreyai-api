from __future__ import annotations

import json
import subprocess
import asyncio
import os
import re
from datetime import datetime
import time
from html import escape
from io import BytesIO
from pathlib import Path
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

from app.transcription.engine import transcribe_audio, normalize_language_code
from app.transcription.formatting import apply_formatting
from app.transcription.formatting_light import minimal_postprocess_ht
from app.transcription.ht_cleanup_pipeline import run_ht_cleanup_pipeline
from app.storage.backend import get_storage
from app.events.recorder import record_event
from app.processing.audio_preprocess import normalize_audio, preprocess_haitian_creole_audio
from app.processing.dispatcher import dispatch_job
from app.services.credits import refund_credit_minutes
from app.config_ht import (
    HT_ENABLE_DIARIZATION_LONG,
    HT_ENABLE_DIARIZATION_SHORT,
    HT_LONG_CHUNK_SECONDS,
    HT_LONG_FORM_MINUTES,
    HT_MAX_CHUNK_SECONDS,
    HT_MEDIUM_CHUNK_SECONDS,
    HT_MIN_CHUNK_SECONDS,
    HT_RESUMABLE_MINUTES,
)

try:
    from app.services.email_service import send_completion_email
except Exception as email_import_error:
    print(f"⚠️ Completion email service unavailable: {email_import_error}")
    send_completion_email = None


db = firestore.Client()
JOBS_COL = "jobs"

# ---------------------------------------------------------
# Chunking config
# ---------------------------------------------------------
CHUNK_IF_LONGER_THAN_SECONDS = 600  # 10 minutes
CHUNK_SIZE_SECONDS = 300            # 5 minutes
HT_CHUNK_IF_LONGER_THAN_SECONDS = int(os.getenv("KREYAI_HT_CHUNK_IF_LONGER_THAN_SECONDS", "600"))
HT_CHUNK_MIN_SECONDS = HT_MIN_CHUNK_SECONDS
HT_CHUNK_TARGET_SECONDS = HT_MEDIUM_CHUNK_SECONDS
HT_CHUNK_MAX_SECONDS = HT_MAX_CHUNK_SECONDS
HT_CHUNK_OVERLAP_SECONDS = 1.5
HT_CHUNK_SILENCE_THRESHOLD_DB = -35
HT_CHUNK_SILENCE_MIN_DURATION_SECONDS = 0.4
PARAGRAPH_BREAK_THRESHOLD = 1.2
HT_RESUME_IF_LONGER_THAN_SECONDS = HT_RESUMABLE_MINUTES * 60
HT_RESUME_BUDGET_SECONDS = 42 * 60
HT_LONG_CHUNK_MIN_SECONDS = max(HT_MIN_CHUNK_SECONDS, HT_LONG_CHUNK_SECONDS - 60)
HT_LONG_CHUNK_TARGET_SECONDS = HT_LONG_CHUNK_SECONDS
HT_LONG_CHUNK_MAX_SECONDS = HT_MAX_CHUNK_SECONDS
HT_SHORT_FORM_MAX_SECONDS = HT_LONG_FORM_MINUTES * 60
HT_MEDIUM_FORM_MAX_SECONDS = HT_RESUMABLE_MINUTES * 60
HT_RESUME_MANIFEST_FILENAME = "ht_resume_manifest.json"
HT_RESUME_RESULTS_FILENAME = "ht_resume_results.json"
HT_RESUME_DIARIZATION_FILENAME = "ht_resume_diarization.json"

SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9.]+)")


class HTResumeRequested(RuntimeError):
    def __init__(self, *, next_chunk_index: int, total_chunks: int):
        super().__init__("HT transcription continuation requested")
        self.next_chunk_index = int(next_chunk_index)
        self.total_chunks = int(total_chunks)


def _transcription_timeout_seconds(
    *,
    language: str,
    audio_duration_seconds: float,
) -> int:
    timeout_seconds = int(PROCESS_ATTEMPT_TIMEOUT_SECONDS)

    if language != "ht":
        return timeout_seconds

    # Long HT runs use many silence-based chunks and can legitimately
    # exceed the generic 30-minute budget even on healthy executions.
    scaled_timeout = int((audio_duration_seconds * 1.25) + (10 * 60))
    return max(timeout_seconds, min(scaled_timeout, 55 * 60))


def _should_run_ht_diarization(
    *,
    duration_seconds: float,
    requested: bool,
) -> bool:
    if not requested:
        return False
    if duration_seconds >= HT_SHORT_FORM_MAX_SECONDS:
        return HT_ENABLE_DIARIZATION_LONG
    return HT_ENABLE_DIARIZATION_SHORT


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


def claim_specific_queued_job(job_id: str) -> Optional[str]:

    jobs_ref = db.collection(JOBS_COL)
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
        print(f"Claimed requested job {job_id}")
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


def _split_transcript_paragraphs(
    text: str,
    *,
    target_chars: int = 420,
    hard_limit_chars: int = 650,
) -> List[str]:

    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return []

    parts: List[str] = []
    remaining = normalized

    while remaining:
        if len(remaining) <= hard_limit_chars:
            parts.append(remaining)
            break

        search_window = remaining[:hard_limit_chars]
        split_at = -1

        if len(search_window) >= target_chars:
            for marker in (". ", "? ", "! ", "; ", ": "):
                idx = search_window.rfind(marker, target_chars // 2)
                if idx > split_at:
                    split_at = idx + len(marker) - 1

        if split_at <= 0:
            split_at = search_window.rfind(" ", target_chars, hard_limit_chars)

        if split_at <= 0:
            split_at = hard_limit_chars

        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()

    return [part for part in parts if part]


def _build_transcript_blocks(
    segments: List[Dict[str, Any]],
) -> List[tuple[str, float, str]]:

    blocks: List[tuple[str, float, str]] = []
    current_speaker = None
    current_start = None
    buffer_parts: List[str] = []

    for seg in segments:
        start = float(seg["start"])
        end = float(seg["end"])
        text = seg["text"].strip()
        speaker = seg.get("speaker")

        if not text:
            continue

        if speaker:
            if current_speaker is None:
                current_speaker = speaker
                current_start = start
                buffer_parts = [text]
            elif speaker == current_speaker:
                buffer_parts.append(text)
            else:
                blocks.append(
                    (str(current_speaker), float(current_start or 0.0), " ".join(buffer_parts).strip())
                )
                current_speaker = speaker
                current_start = start
                buffer_parts = [text]
        else:
            if buffer_parts:
                blocks.append(
                    (
                        str(current_speaker or "Speaker"),
                        float(current_start or 0.0),
                        " ".join(buffer_parts).strip(),
                    )
                )
                current_speaker = None
                current_start = None
                buffer_parts = []
            blocks.append(("Speaker", start, text))

        _ = end

    if buffer_parts:
        blocks.append(
            (
                str(current_speaker or "Speaker"),
                float(current_start or 0.0),
                " ".join(buffer_parts).strip(),
            )
        )

    return blocks


def _build_transcript_text(
    segments: List[Dict[str, Any]],
    *,
    language: Optional[str] = None,
) -> str:

    lines: List[str] = []

    for speaker, time_value, text in _build_transcript_blocks(segments):
        lines.append(f"{speaker} ({_format_hhmmss(time_value)})")
        formatted_text = (
            minimal_postprocess_ht(text)
            if language == "ht"
            else apply_formatting(text, language=language)
        )
        for paragraph in _split_transcript_paragraphs(formatted_text):
            lines.append(paragraph)
        lines.append("")

    return "\n".join(lines).strip() + "\n" if lines else ""


def _has_speaker_labels(segments: List[Dict[str, Any]]) -> bool:
    return any((seg.get("speaker") or "").strip() for seg in segments)


def _build_plain_paragraph_transcript(
    segments: List[Dict[str, Any]],
    *,
    paragraph_break_threshold: float = PARAGRAPH_BREAK_THRESHOLD,
    language: Optional[str] = None,
) -> str:

    paragraphs: List[str] = []
    current_paragraph: List[str] = []
    last_end: Optional[float] = None

    for seg in segments:
        text = " ".join(str(seg.get("text") or "").split()).strip()
        start = seg.get("start")
        end = seg.get("end")

        if not text:
            continue

        start_value = float(start) if start is not None else None
        end_value = float(end) if end is not None else None

        if (
            current_paragraph
            and last_end is not None
            and start_value is not None
            and (start_value - last_end) > paragraph_break_threshold
        ):
            joined_paragraph = " ".join(current_paragraph)
            paragraph_text = (
                minimal_postprocess_ht(joined_paragraph).strip()
                if language == "ht"
                else apply_formatting(joined_paragraph, language=language).strip()
            )
            if paragraph_text:
                paragraphs.append(paragraph_text)
            current_paragraph = [text]
        else:
            current_paragraph.append(text)

        if end_value is not None:
            last_end = end_value

    if current_paragraph:
        joined_paragraph = " ".join(current_paragraph)
        paragraph_text = (
            minimal_postprocess_ht(joined_paragraph).strip()
            if language == "ht"
            else apply_formatting(joined_paragraph, language=language).strip()
        )
        if paragraph_text:
            paragraphs.append(paragraph_text)

    return "\n\n".join(paragraphs).strip() + "\n" if paragraphs else ""


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


def split_audio_into_chunks(file_path: str, chunk_seconds: int = CHUNK_SIZE_SECONDS) -> List[str]:
    """
    Split audio into mono 16k wav chunks.
    """
    chunk_dir = f"{file_path}_chunks"
    os.makedirs(chunk_dir, exist_ok=True)

    output_pattern = os.path.join(chunk_dir, "chunk_%03d.wav")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        file_path,
        "-f",
        "segment",
        "-segment_time",
        str(chunk_seconds),
        "-ar",
        "16000",
        "-ac",
        "1",
        output_pattern,
    ]

    subprocess.run(cmd, check=True, capture_output=True)

    chunk_paths = sorted(
        os.path.join(chunk_dir, name)
        for name in os.listdir(chunk_dir)
        if name.startswith("chunk_") and name.endswith(".wav")
    )

    if not chunk_paths:
        raise RuntimeError("Audio chunking produced no output files")

    return chunk_paths


def _extract_audio_chunk(output_path: str, file_path: str, start_time: float, end_time: float) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{max(0.0, start_time):.3f}",
        "-to",
        f"{max(start_time, end_time):.3f}",
        "-i",
        file_path,
        "-ar",
        "16000",
        "-ac",
        "1",
        output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _detect_silence_endings(
    file_path: str,
    *,
    noise_db: int = HT_CHUNK_SILENCE_THRESHOLD_DB,
    min_silence_seconds: float = HT_CHUNK_SILENCE_MIN_DURATION_SECONDS,
) -> List[float]:
    cmd = [
        "ffmpeg",
        "-i",
        file_path,
        "-af",
        f"silencedetect=noise={noise_db}dB:d={min_silence_seconds}",
        "-f",
        "null",
        "-",
    ]

    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    silence_ends: List[float] = []

    for match in SILENCE_END_RE.finditer(completed.stderr or ""):
        try:
            silence_ends.append(float(match.group(1)))
        except ValueError:
            continue

    return sorted(set(silence_ends))


def build_silence_chunk_specs(
    file_path: str,
    *,
    total_duration: float,
    min_chunk_seconds: int = HT_CHUNK_MIN_SECONDS,
    target_chunk_seconds: int = HT_CHUNK_TARGET_SECONDS,
    max_chunk_seconds: int = HT_CHUNK_MAX_SECONDS,
    overlap_seconds: float = HT_CHUNK_OVERLAP_SECONDS,
    output_dir: str | None = None,
) -> List[Dict[str, Any]]:
    """
    Split audio into HT-friendly chunks that prefer pause boundaries.
    Each chunk keeps a small overlap, but also records the core keep window
    so merged output does not duplicate overlap text.
    """
    chunk_dir = output_dir or f"{file_path}_ht_chunks"
    os.makedirs(chunk_dir, exist_ok=True)

    silence_ends = _detect_silence_endings(file_path)
    silence_ends = [value for value in silence_ends if 0.0 < value < total_duration]

    boundaries = [0.0]
    current = 0.0

    while current < total_duration:
        remaining = total_duration - current
        if remaining <= max_chunk_seconds:
            boundaries.append(total_duration)
            break

        window_start = current + min_chunk_seconds
        window_end = min(total_duration, current + max_chunk_seconds)
        candidates = [value for value in silence_ends if window_start <= value <= window_end]

        if candidates:
            cut_time = min(candidates, key=lambda value: abs(value - (current + target_chunk_seconds)))
        else:
            cut_time = window_end

        if cut_time <= current:
            cut_time = min(total_duration, current + max_chunk_seconds)

        boundaries.append(cut_time)
        current = cut_time

    chunk_specs: List[Dict[str, Any]] = []

    for index in range(len(boundaries) - 1):
        keep_start = boundaries[index]
        keep_end = boundaries[index + 1]
        chunk_start = max(0.0, keep_start - overlap_seconds)
        chunk_end = min(total_duration, keep_end + overlap_seconds)
        output_path = os.path.join(chunk_dir, f"chunk_{index:03d}.wav")
        _extract_audio_chunk(output_path, file_path, chunk_start, chunk_end)
        chunk_specs.append(
            {
                "path": output_path,
                "chunk_start": chunk_start,
                "chunk_end": chunk_end,
                "keep_start": keep_start,
                "keep_end": keep_end,
            }
        )

    if not chunk_specs:
        raise RuntimeError("Silence-based chunking produced no output files")

    return chunk_specs


def split_audio_into_silence_chunks(
    file_path: str,
    *,
    total_duration: float,
    min_chunk_seconds: int = HT_CHUNK_MIN_SECONDS,
    target_chunk_seconds: int = HT_CHUNK_TARGET_SECONDS,
    max_chunk_seconds: int = HT_CHUNK_MAX_SECONDS,
    overlap_seconds: float = HT_CHUNK_OVERLAP_SECONDS,
) -> List[Dict[str, Any]]:
    return build_silence_chunk_specs(
        file_path,
        total_duration=total_duration,
        min_chunk_seconds=min_chunk_seconds,
        target_chunk_seconds=target_chunk_seconds,
        max_chunk_seconds=max_chunk_seconds,
        overlap_seconds=overlap_seconds,
    )


def _ht_resume_enabled() -> bool:
    return os.getenv("KREYAI_HT_RESUME_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def _load_output_json(storage, job_id: str, filename: str) -> Any | None:
    if not storage.output_exists(job_id, filename):
        return None
    raw = storage.read_output_text(job_id, filename)
    if not raw.strip():
        return None
    return json.loads(raw)


def _save_output_json(storage, job_id: str, filename: str, payload: Any) -> None:
    storage.save_output_text(
        job_id,
        filename,
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        content_type="application/json; charset=utf-8",
    )


def _cleanup_ht_resume_outputs(storage, job_id: str) -> None:
    for filename in (
        HT_RESUME_MANIFEST_FILENAME,
        HT_RESUME_RESULTS_FILENAME,
        HT_RESUME_DIARIZATION_FILENAME,
    ):
        try:
            storage.delete_output(job_id, filename)
        except Exception:
            pass


def _persist_ht_resume_state(
    doc_ref,
    *,
    next_chunk_index: int,
    total_chunks: int,
    last_completed_chunk_index: int | None,
) -> None:
    updates: Dict[str, Any] = {
        "ht_resume_next_chunk_index": int(next_chunk_index),
        "ht_resume_total_chunks": int(total_chunks),
        "updated_at": datetime.utcnow().isoformat(),
    }
    if last_completed_chunk_index is not None:
        updates["ht_resume_last_completed_chunk_index"] = int(last_completed_chunk_index)
    doc_ref.update(updates)


def _clear_ht_resume_state(doc_ref) -> None:
    doc_ref.update(
        {
            "ht_resume_next_chunk_index": firestore.DELETE_FIELD,
            "ht_resume_total_chunks": firestore.DELETE_FIELD,
            "ht_resume_last_completed_chunk_index": firestore.DELETE_FIELD,
        }
    )


def _queue_ht_resume(
    doc_ref,
    job_id: str,
    job: Dict[str, Any],
    *,
    next_chunk_index: int,
    total_chunks: int,
) -> None:
    _persist_ht_resume_state(
        doc_ref,
        next_chunk_index=next_chunk_index,
        total_chunks=total_chunks,
        last_completed_chunk_index=max(-1, next_chunk_index - 1),
    )
    doc_ref.update(
        {
            "status": JobStatus.QUEUED.value,
            "status_message": f"Continuing HT transcription in next worker pass ({next_chunk_index}/{total_chunks} chunks complete)",
            "progress": 55 + int((max(0, min(total_chunks, next_chunk_index)) / max(1, total_chunks)) * 19),
            "ht_resume_execution_count": firestore.Increment(1),
            "updated_at": datetime.utcnow().isoformat(),
        }
    )
    record_event(
        job_id,
        "requeued",
        f"Continuing HT transcription from chunk {next_chunk_index + 1} of {total_chunks}",
        JobStatus.QUEUED.value,
    )
    dispatch_job(
        job_id,
        worker_job_name=str(job.get("worker_job_name") or "kreyai-worker-gpu"),
        worker_job_region=str(job.get("worker_job_region") or os.environ.get("CLOUD_RUN_REGION", "us-central1")),
        execution_lane=str(job.get("execution_lane") or "gpu"),
        requires_diarization=bool(job.get("requires_diarization")),
    )


async def transcribe_ht_with_resumable_chunking(
    file_path: str,
    *,
    job_id: str,
    storage,
    doc_ref,
    job: Dict[str, Any],
    progress_cb=None,
    budget_seconds: int = HT_RESUME_BUDGET_SECONDS,
) -> Dict[str, Any]:

    def emit_progress(pct: int, message: str) -> None:
        if callable(progress_cb):
            try:
                progress_cb(int(pct), str(message))
            except Exception:
                pass

    total_duration = get_audio_duration_seconds(file_path)
    manifest = _load_output_json(storage, job_id, HT_RESUME_MANIFEST_FILENAME)
    if not isinstance(manifest, list) or not manifest:
        emit_progress(5, "Preparing resumable Haitian Creole chunks")
        built_specs = build_silence_chunk_specs(
            file_path,
            total_duration=total_duration,
            min_chunk_seconds=HT_LONG_CHUNK_MIN_SECONDS,
            target_chunk_seconds=HT_LONG_CHUNK_TARGET_SECONDS,
            max_chunk_seconds=HT_LONG_CHUNK_MAX_SECONDS,
            output_dir=f"{file_path}_ht_manifest_chunks",
        )
        try:
            manifest = [
                {
                    "chunk_start": float(spec["chunk_start"]),
                    "chunk_end": float(spec["chunk_end"]),
                    "keep_start": float(spec["keep_start"]),
                    "keep_end": float(spec["keep_end"]),
                }
                for spec in built_specs
            ]
        finally:
            cleanup_chunk_files(built_specs)
        _save_output_json(storage, job_id, HT_RESUME_MANIFEST_FILENAME, manifest)

    stored_results = _load_output_json(storage, job_id, HT_RESUME_RESULTS_FILENAME)
    chunk_results: List[Dict[str, Any]] = stored_results if isinstance(stored_results, list) else []
    total_chunks = max(1, len(manifest))
    start_index = min(len(chunk_results), total_chunks)
    _persist_ht_resume_state(
        doc_ref,
        next_chunk_index=start_index,
        total_chunks=total_chunks,
        last_completed_chunk_index=(start_index - 1) if start_index > 0 else None,
    )

    started_at = time.time()
    materialized_chunk_specs: List[Dict[str, Any]] = []

    try:
        for index in range(start_index, total_chunks):
            if index > start_index and (time.time() - started_at) >= budget_seconds:
                _save_output_json(storage, job_id, HT_RESUME_RESULTS_FILENAME, chunk_results)
                raise HTResumeRequested(next_chunk_index=index, total_chunks=total_chunks)

            chunk_meta = manifest[index]
            output_path = f"{file_path}_ht_resume_chunk_{index:03d}.wav"
            _extract_audio_chunk(
                output_path,
                file_path,
                float(chunk_meta["chunk_start"]),
                float(chunk_meta["chunk_end"]),
            )
            materialized_chunk_specs.append({"path": output_path})

            chunk_start = int((index / total_chunks) * 100)
            chunk_end = int(((index + 1) / total_chunks) * 100)

            def chunk_progress(pct: int, message: str) -> None:
                scaled_pct = chunk_start + int((max(0, min(100, pct)) / 100) * (chunk_end - chunk_start))
                emit_progress(
                    scaled_pct,
                    f"Transcribing HT chunk {index + 1}/{total_chunks}: {message}",
                )

            result = await asyncio.to_thread(
                transcribe_audio,
                output_path,
                language="ht",
                progress_cb=chunk_progress,
            )
            chunk_results.append(result)
            _save_output_json(storage, job_id, HT_RESUME_RESULTS_FILENAME, chunk_results)
            _persist_ht_resume_state(
                doc_ref,
                next_chunk_index=index + 1,
                total_chunks=total_chunks,
                last_completed_chunk_index=index,
            )

        _cleanup_ht_resume_outputs(storage, job_id)
        return merge_chunk_results(chunk_results, manifest)
    finally:
        cleanup_chunk_files(materialized_chunk_specs)


def cleanup_chunk_files(chunk_paths: List[str] | List[Dict[str, Any]]) -> None:
    if not chunk_paths:
        return

    normalized_paths = [
        item.get("path") if isinstance(item, dict) else item
        for item in chunk_paths
    ]

    for path in normalized_paths:
        if not path:
            continue
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    first_path = next((path for path in normalized_paths if path), None)
    if not first_path:
        return

    chunk_dir = os.path.dirname(first_path)
    try:
        if os.path.isdir(chunk_dir) and not os.listdir(chunk_dir):
            os.rmdir(chunk_dir)
    except Exception:
        pass


def merge_chunk_results(
    chunk_results: List[Dict[str, Any]],
    chunk_ranges: List[Dict[str, Any]],
) -> Dict[str, Any]:

    merged_segments: List[Dict[str, Any]] = []
    merged_language = None
    merged_detected_language = None
    merged_requested_language = None

    for result, chunk_range in zip(chunk_results, chunk_ranges):
        if merged_language is None:
            merged_language = result.get("language")
        if merged_detected_language is None:
            merged_detected_language = result.get("language_detected")
        if merged_requested_language is None:
            merged_requested_language = result.get("language_requested")

        offset = float(chunk_range.get("chunk_start", 0.0))
        keep_start = float(chunk_range.get("keep_start", offset))
        keep_end = float(chunk_range.get("keep_end", chunk_range.get("chunk_end", offset)))

        for seg in _segments_from_result(result):
            seg_start = float(seg.get("start", 0.0)) + offset
            seg_end = float(seg.get("end", 0.0)) + offset
            seg_midpoint = seg_start + ((seg_end - seg_start) / 2.0)

            if seg_midpoint < keep_start or seg_midpoint > keep_end:
                continue

            merged_words = []
            for word in seg.get("words") or []:
                if not isinstance(word, dict):
                    continue

                word_start = word.get("start")
                word_end = word.get("end")
                absolute_word_start = float(word_start) + offset if word_start is not None else None
                absolute_word_end = float(word_end) + offset if word_end is not None else None

                if absolute_word_start is not None and absolute_word_end is not None:
                    word_midpoint = absolute_word_start + ((absolute_word_end - absolute_word_start) / 2.0)
                    if word_midpoint < keep_start or word_midpoint > keep_end:
                        continue

                merged_words.append(
                    {
                        **word,
                        "start": absolute_word_start,
                        "end": absolute_word_end,
                    }
                )

            merged_segments.append(
                {
                    "start": seg_start,
                    "end": seg_end,
                    "text": (seg.get("text") or "").strip(),
                    "words": merged_words,
                }
            )

    merged_text_parts = [
        (seg.get("text") or "").strip()
        for seg in merged_segments
        if (seg.get("text") or "").strip()
    ]

    return {
        "text": " ".join(merged_text_parts).strip(),
        "segments": merged_segments,
        "language": merged_language,
        "language_detected": merged_detected_language,
        "language_requested": merged_requested_language,
    }


async def transcribe_with_optional_chunking(
    file_path: str,
    language: str,
    *,
    progress_cb=None,
    storage=None,
    job_id: str | None = None,
    doc_ref=None,
    job: Dict[str, Any] | None = None,
) -> Dict[str, Any]:

    def emit_progress(pct: int, message: str) -> None:
        if callable(progress_cb):
            try:
                progress_cb(int(pct), str(message))
            except Exception:
                pass

    total_duration = get_audio_duration_seconds(file_path)

    if (
        language == "ht"
        and total_duration > HT_RESUME_IF_LONGER_THAN_SECONDS
        and _ht_resume_enabled()
        and storage is not None
        and job_id
        and doc_ref is not None
        and job is not None
    ):
        return await transcribe_ht_with_resumable_chunking(
            file_path,
            job_id=job_id,
            storage=storage,
            doc_ref=doc_ref,
            job=job,
            progress_cb=progress_cb,
        )

    if language == "ht" and total_duration > HT_CHUNK_IF_LONGER_THAN_SECONDS:
        emit_progress(5, "Preparing silence-based Haitian Creole chunks")
        if total_duration <= HT_SHORT_FORM_MAX_SECONDS:
            target_seconds = HT_CHUNK_TARGET_SECONDS
            min_seconds = max(45, min(HT_CHUNK_MIN_SECONDS, target_seconds))
            max_seconds = min(180, HT_CHUNK_MAX_SECONDS)
        else:
            target_seconds = HT_MEDIUM_CHUNK_SECONDS
            min_seconds = HT_MIN_CHUNK_SECONDS
            max_seconds = min(HT_MAX_CHUNK_SECONDS, max(target_seconds + 60, HT_MEDIUM_CHUNK_SECONDS))

        chunk_specs = split_audio_into_silence_chunks(
            file_path,
            total_duration=total_duration,
            min_chunk_seconds=min_seconds,
            target_chunk_seconds=target_seconds,
            max_chunk_seconds=max_seconds,
        )

        try:
            chunk_results: List[Dict[str, Any]] = []
            total_chunks = max(1, len(chunk_specs))

            for index, chunk_spec in enumerate(chunk_specs):
                chunk_start = int((index / total_chunks) * 100)
                chunk_end = int(((index + 1) / total_chunks) * 100)

                def chunk_progress(pct: int, message: str) -> None:
                    scaled_pct = chunk_start + int((max(0, min(100, pct)) / 100) * (chunk_end - chunk_start))
                    emit_progress(
                        scaled_pct,
                        f"Transcribing HT chunk {index + 1}/{total_chunks}: {message}",
                    )

                result = await asyncio.to_thread(
                    transcribe_audio,
                    chunk_spec["path"],
                    language=language,
                    progress_cb=chunk_progress,
                )
                chunk_results.append(result)

            return merge_chunk_results(chunk_results, chunk_specs)
        finally:
            cleanup_chunk_files(chunk_specs)

    if total_duration <= CHUNK_IF_LONGER_THAN_SECONDS:
        return await asyncio.to_thread(
            transcribe_audio,
            file_path,
            language=language,
            progress_cb=progress_cb,
        )

    print(
        f"Audio exceeds {CHUNK_IF_LONGER_THAN_SECONDS}s; "
        f"chunking into {CHUNK_SIZE_SECONDS}s segments"
    )

    chunk_paths = split_audio_into_chunks(file_path, CHUNK_SIZE_SECONDS)

    try:

        chunk_results: List[Dict[str, Any]] = []
        chunk_ranges: List[Dict[str, Any]] = []
        offset = 0.0

        total_chunks = max(1, len(chunk_paths))

        for index, chunk_path in enumerate(chunk_paths):

            duration = get_audio_duration_seconds(chunk_path)
            chunk_ranges.append(
                {
                    "chunk_start": offset,
                    "chunk_end": offset + duration,
                    "keep_start": offset,
                    "keep_end": offset + duration,
                }
            )
            offset += duration

            chunk_start = int((index / total_chunks) * 100)
            chunk_end = int(((index + 1) / total_chunks) * 100)

            def chunk_progress(pct: int, message: str) -> None:
                scaled_pct = chunk_start + int((max(0, min(100, pct)) / 100) * (chunk_end - chunk_start))
                emit_progress(
                    scaled_pct,
                    f"Transcribing chunk {index + 1}/{total_chunks}: {message}",
                )

            result = await asyncio.to_thread(
                transcribe_audio,
                chunk_path,
                language=language,
                progress_cb=chunk_progress,
            )

            chunk_results.append(result)

        return merge_chunk_results(chunk_results, chunk_ranges)

    finally:
        cleanup_chunk_files(chunk_paths)


# ---------------------------------------------------------
# Cost Estimation
# ---------------------------------------------------------
def estimate_cost_usd(audio_duration_seconds: float) -> float:
    """
    Conservative placeholder estimate.
    Refine later using real observed GCP costs.
    """

    estimated = audio_duration_seconds * 0.0008

    return round(estimated, 4)


# ---------------------------------------------------------
# Align Whisper segments with diarization speakers
# ---------------------------------------------------------
def _find_best_speaker(
    start: float,
    end: float,
    speaker_segments: List[Dict[str, Any]],
) -> Optional[str]:

    mid = (start + end) / 2
    best_speaker = None
    best_overlap = 0.0

    for spk in speaker_segments:
        spk_start = float(spk.get("start", 0.0))
        spk_end = float(spk.get("end", 0.0))
        overlap = min(end, spk_end) - max(start, spk_start)

        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = spk.get("speaker")

    if best_speaker:
        return str(best_speaker)

    closest_speaker = None
    closest_distance = float("inf")

    for spk in speaker_segments:
        spk_mid = (float(spk.get("start", 0.0)) + float(spk.get("end", 0.0))) / 2
        distance = abs(mid - spk_mid)

        if distance < closest_distance:
            closest_distance = distance
            closest_speaker = spk.get("speaker")

    return str(closest_speaker) if closest_speaker else None


def _combine_words_text(words: List[Dict[str, Any]]) -> str:
    return "".join(str(word.get("word") or "") for word in words).strip()


def _normalize_text_for_alignment(text: str) -> str:
    return "".join(
        ch.lower()
        for ch in str(text or "")
        if ch.isalnum()
    )


def _split_segment_by_speaker(
    seg: Dict[str, Any],
    speaker_segments: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:

    seg_start = float(seg.get("start", 0.0))
    seg_end = float(seg.get("end", 0.0))
    seg_text = (seg.get("text") or "").strip()
    words = [
        word for word in (seg.get("words") or [])
        if isinstance(word, dict) and (word.get("word") or "").strip()
    ]

    if not words:
        speaker = _find_best_speaker(seg_start, seg_end, speaker_segments)
        split_seg = dict(seg)
        if speaker:
            split_seg["speaker"] = speaker
        return [split_seg]

    combined_words_text = _combine_words_text(words)
    if (
        _normalize_text_for_alignment(seg_text)
        and _normalize_text_for_alignment(combined_words_text)
        and _normalize_text_for_alignment(seg_text)
        != _normalize_text_for_alignment(combined_words_text)
    ):
        speaker = _find_best_speaker(seg_start, seg_end, speaker_segments)
        split_seg = dict(seg)
        if speaker:
            split_seg["speaker"] = speaker
        return [split_seg]

    annotated_words: List[Dict[str, Any]] = []
    for word in words:
        word_start = word.get("start")
        word_end = word.get("end")

        if word_start is None or word_end is None:
            speaker = _find_best_speaker(seg_start, seg_end, speaker_segments)
        else:
            speaker = _find_best_speaker(float(word_start), float(word_end), speaker_segments)

        annotated_words.append({**word, "speaker": speaker})

    split_segments: List[Dict[str, Any]] = []
    current_words: List[Dict[str, Any]] = []
    current_speaker: Optional[str] = None

    def flush() -> None:
        nonlocal current_words, current_speaker
        if not current_words:
            return

        split_text = _combine_words_text(current_words) or seg_text
        split_start = current_words[0].get("start")
        split_end = current_words[-1].get("end")

        split_seg = {
            "start": float(split_start) if split_start is not None else seg_start,
            "end": float(split_end) if split_end is not None else seg_end,
            "text": split_text,
            "words": [{k: v for k, v in word.items() if k != "speaker"} for word in current_words],
        }
        if current_speaker:
            split_seg["speaker"] = current_speaker
        split_segments.append(split_seg)
        current_words = []
        current_speaker = None

    for word in annotated_words:
        word_speaker = word.get("speaker")
        if current_words and word_speaker != current_speaker:
            flush()

        if not current_words:
            current_speaker = str(word_speaker) if word_speaker else None

        current_words.append(word)

    flush()

    if not split_segments:
        split_seg = dict(seg)
        speaker = _find_best_speaker(seg_start, seg_end, speaker_segments)
        if speaker:
            split_seg["speaker"] = speaker
        return [split_seg]

    return split_segments


def align_speakers(result: Dict[str, Any], speaker_segments: List[Dict[str, Any]]) -> None:
    """
    Split transcript segments on speaker changes and attach speaker labels using
    diarization overlap, with midpoint fallback when overlap is ambiguous.
    """

    if not speaker_segments:
        return

    segments = _segments_from_result(result)
    split_segments: List[Dict[str, Any]] = []

    for seg in segments:
        split_segments.extend(_split_segment_by_speaker(seg, speaker_segments))

    result["segments"] = split_segments


def _count_speaker_labeled_segments(result: Dict[str, Any]) -> int:

    return sum(
        1
        for seg in _segments_from_result(result)
        if (seg.get("speaker") or "").strip()
    )

# ---------------------------------------------------------
# Run Job
# ---------------------------------------------------------
async def run_job(job_id: str):

    doc_ref = db.collection(JOBS_COL).document(job_id)
    snap = doc_ref.get()

    if not snap.exists:
        return

    job = snap.to_dict() or {}
    progress = int(job.get("progress") or 0)

    def update_progress(next_progress: int, message: str) -> None:
        nonlocal progress
        progress = max(progress, int(next_progress))
        doc_ref.update(
            {
                "status": JobStatus.PROCESSING.value,
                "progress": progress,
                "status_message": message,
                "updated_at": datetime.utcnow().isoformat(),
            }
        )

    attempts = int(job.get("attempts") or 0)
    resume_in_progress = int(job.get("ht_resume_next_chunk_index") or 0) > 0

    if attempts >= PROCESS_MAX_ATTEMPTS and not resume_in_progress:

        doc_ref.update(
            {
                "status": JobStatus.FAILED.value,
                "status_message": "Max attempts reached",
                "updated_at": datetime.utcnow().isoformat(),
            }
        )

        return

    start_updates: Dict[str, Any] = {
        "status": JobStatus.PROCESSING.value,
        "progress": max(progress, 5),
        "status_message": "Starting" if not resume_in_progress else "Resuming HT transcription",
        "updated_at": datetime.utcnow().isoformat(),
    }
    if not resume_in_progress:
        start_updates["attempts"] = attempts + 1
    else:
        start_updates["ht_resume_execution_count"] = firestore.Increment(1)

    doc_ref.update(start_updates)
    progress = max(progress, 5)

    local_path = None
    processed_local_path = None
    diarization_input_path = None

    try:

        start_time = time.time()
        file_size_bytes = None
        audio_duration_seconds = None
        processing_time_seconds = None
        estimated_cost_value = None
        realtime_factor = None
        download_time_seconds = None
        diarization_time_seconds = None
        transcription_time_seconds = None
        alignment_time_seconds = None
        output_time_seconds = None
        diarization_error_message = None
        diarization_status = "not_started"
        speaker_segments: List[Dict[str, Any]] = []
        labeled_segments_count = 0

        storage = get_storage()

        source_blob = job.get("file_path") or job.get("upload_path")
        requested_language = normalize_language_code(job.get("language", "auto")) or "auto"
        requires_diarization = bool(job.get("requires_diarization"))

        if not source_blob:
            raise RuntimeError("Job missing storage path")

        source_suffix = Path(str(source_blob)).suffix
        local_path = f"/tmp/{job_id}_input{source_suffix}" if source_suffix else f"/tmp/{job_id}_input"

        update_progress(10, "Downloading upload")
        download_start_time = time.time()
        storage.download_to_file(source_blob, local_path)
        download_time_seconds = round(time.time() - download_start_time, 3)

        processed_local_path = local_path
        if requested_language == "ht":
            update_progress(18, "Preprocessing Haitian Creole audio")
            processed_local_path = await asyncio.to_thread(
                preprocess_haitian_creole_audio,
                local_path,
            )

        if os.path.exists(local_path):
            file_size_bytes = os.path.getsize(local_path)

        duration = get_audio_duration_seconds(processed_local_path)
        audio_duration_seconds = duration
        effective_requires_diarization = requires_diarization
        if requested_language == "ht":
            effective_requires_diarization = _should_run_ht_diarization(
                duration_seconds=duration,
                requested=requires_diarization,
            )

        print(f"Audio duration: {duration} seconds")

        if duration > MAX_AUDIO_DURATION_SECONDS:
            raise RuntimeError(
                f"Audio exceeds maximum allowed duration ({MAX_AUDIO_DURATION_SECONDS} seconds)"
            )

        # ---------------------------------------------------------
        # Run speaker diarization before transcription when requested
        # ---------------------------------------------------------
        ht_resume_diarization_eligible = (
            requested_language == "ht"
            and _ht_resume_enabled()
            and effective_requires_diarization
        )

        if effective_requires_diarization:
            from app.transcription.diarization import (
                diarize_audio,
                get_diarization_configuration_error,
            )

            update_progress(25, "Analyzing speakers")
            cached_diarization = None
            if ht_resume_diarization_eligible:
                cached_diarization = _load_output_json(
                    storage,
                    job_id,
                    HT_RESUME_DIARIZATION_FILENAME,
                )

            if isinstance(cached_diarization, list):
                speaker_segments = cached_diarization
                diarization_status = (
                    "completed" if speaker_segments else "completed_empty"
                )
                diarization_time_seconds = 0.0
                print(f"Reusing cached diarization segments: {len(speaker_segments)}")
            else:
                diarization_config_error = get_diarization_configuration_error()
                if diarization_config_error:
                    diarization_error_message = diarization_config_error
                    diarization_status = "misconfigured"
                    diarization_time_seconds = 0.0
                    print(
                        "Skipping speaker diarization due to configuration issue:",
                        diarization_error_message,
                    )
                else:
                    try:
                        print("Running speaker diarization...")
                        diarization_start_time = time.time()
                        # Diarization needs a WAV-like audio stream even when
                        # HT transcription intentionally uses the original
                        # upload to avoid damaging ASR quality.
                        diarization_input_path = await asyncio.to_thread(
                            normalize_audio,
                            local_path,
                        )
                        speaker_segments = await asyncio.to_thread(
                            diarize_audio,
                            diarization_input_path
                        )
                        diarization_time_seconds = round(time.time() - diarization_start_time, 3)
                        print(f"Diarization segments detected: {len(speaker_segments)}")
                        diarization_status = (
                            "completed" if speaker_segments else "completed_empty"
                        )
                        if ht_resume_diarization_eligible:
                            _save_output_json(
                                storage,
                                job_id,
                                HT_RESUME_DIARIZATION_FILENAME,
                                speaker_segments,
                            )
                    except Exception as diarization_error:
                        diarization_time_seconds = round(time.time() - diarization_start_time, 3)
                        print("Diarization failed but continuing transcription:", diarization_error)
                        diarization_error_message = str(diarization_error)
                        lowered_diarization_error = diarization_error_message.lower()
                        if "hf_token" in lowered_diarization_error or "hugging face" in lowered_diarization_error:
                            diarization_status = "misconfigured"
                        else:
                            diarization_status = "failed"
                        speaker_segments = []
        else:
            diarization_status = "skipped"
            diarization_time_seconds = 0.0
        # ---------------------------------------------------------

        update_progress(55, "Transcribing audio")
        transcription_start_time = time.time()

        def transcription_progress(next_progress: int, message: str) -> None:
            bounded_progress = max(0, min(100, int(next_progress)))
            mapped_progress = 55 + int((bounded_progress / 100) * 19)
            update_progress(mapped_progress, message)

        transcription_timeout_seconds = _transcription_timeout_seconds(
            language=requested_language,
            audio_duration_seconds=duration,
        )
        print(
            "Transcription timeout budget:",
            transcription_timeout_seconds,
            "seconds",
        )

        result = await asyncio.wait_for(
            transcribe_with_optional_chunking(
                processed_local_path,
                language=requested_language,
                progress_cb=transcription_progress,
                storage=storage,
                job_id=job_id,
                doc_ref=doc_ref,
                job=job,
            ),
            timeout=transcription_timeout_seconds,
        )
        transcription_time_seconds = round(time.time() - transcription_start_time, 3)
        final_language = result.get("language") or requested_language
        detected_language = result.get("language_detected")

        update_progress(75, "Preparing transcript")
        alignment_start_time = time.time()
        if effective_requires_diarization and speaker_segments:
            align_speakers(result, speaker_segments)
        alignment_time_seconds = round(time.time() - alignment_start_time, 3)
        result["speaker_segments"] = speaker_segments
        result["diarization"] = {
            "status": diarization_status,
            "error": diarization_error_message,
        }
        labeled_segments_count = _count_speaker_labeled_segments(result)

        update_progress(90, "Saving transcript files")
        output_start_time = time.time()
        save_outputs(storage, job_id, result)
        output_time_seconds = round(time.time() - output_start_time, 3)

        processing_time_seconds = round(time.time() - start_time, 3)
        estimated_cost_value = estimate_cost_usd(audio_duration_seconds or 0.0)

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
                "download_time_seconds": download_time_seconds,
                "diarization_time_seconds": diarization_time_seconds,
                "transcription_time_seconds": transcription_time_seconds,
                "alignment_time_seconds": alignment_time_seconds,
                "output_time_seconds": output_time_seconds,
                "estimated_cost_usd": estimated_cost_value,
                "realtime_factor": realtime_factor,
                "model": "faster-whisper",
                "language_requested": requested_language,
                "language_final": final_language,
                "language_detected": detected_language,
                "diarization_status": diarization_status,
                "diarization_error": diarization_error_message,
                "diarization_segments_count": len(speaker_segments),
                "speaker_labeled_segments_count": labeled_segments_count,
                "requires_diarization": effective_requires_diarization,
                "ht_resume_next_chunk_index": firestore.DELETE_FIELD,
                "ht_resume_total_chunks": firestore.DELETE_FIELD,
                "ht_resume_last_completed_chunk_index": firestore.DELETE_FIELD,
            }
        )

        if send_completion_email and job.get("email"):

            try:
                await send_completion_email(
                    job["email"],
                    job_id,
                    language=final_language,
                )
            except Exception as e:
                print("Email error", e)

    except HTResumeRequested as resume_request:
        try:
            _queue_ht_resume(
                doc_ref,
                job_id,
                job,
                next_chunk_index=resume_request.next_chunk_index,
                total_chunks=resume_request.total_chunks,
            )
        except Exception as dispatch_error:
            failure_message = f"Failed to continue HT transcription: {dispatch_error}"
            doc_ref.update(
                {
                    "status": JobStatus.FAILED.value,
                    "status_message": failure_message,
                    "updated_at": datetime.utcnow().isoformat(),
                }
            )
            record_event(job_id, "failed", failure_message, JobStatus.FAILED.value)
            raise
    except BaseException as e:
        charged_minutes = int(job.get("credits_charged_minutes") or 0)
        if charged_minutes > 0:
            try:
                refund_credit_minutes(
                    email=str(job.get("email") or ""),
                    minutes=charged_minutes,
                    idempotency_key=f"job_refund_failure:{job_id}",
                    source="processing_failure",
                    description=f"Returned credits after failed job {job_id}",
                    metadata={"job_id": job_id},
                )
            except Exception as refund_error:
                print(f"⚠️ Credit refund failed for {job_id}: {refund_error}")

        failure_message = str(e) or e.__class__.__name__
        if isinstance(e, asyncio.TimeoutError):
            failure_message = "Transcription timed out"
        elif isinstance(e, asyncio.CancelledError):
            failure_message = "Transcription was cancelled"

        failure_update = {
            "status": JobStatus.FAILED.value,
            "status_message": failure_message,
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
            if download_time_seconds is not None:
                failure_update["download_time_seconds"] = download_time_seconds
            if diarization_time_seconds is not None:
                failure_update["diarization_time_seconds"] = diarization_time_seconds
            if transcription_time_seconds is not None:
                failure_update["transcription_time_seconds"] = transcription_time_seconds
            if alignment_time_seconds is not None:
                failure_update["alignment_time_seconds"] = alignment_time_seconds
            if output_time_seconds is not None:
                failure_update["output_time_seconds"] = output_time_seconds
            if realtime_factor is not None:
                failure_update["realtime_factor"] = realtime_factor
            failure_update["diarization_status"] = diarization_status
            failure_update["diarization_error"] = diarization_error_message
            failure_update["diarization_segments_count"] = len(speaker_segments)
            failure_update["speaker_labeled_segments_count"] = labeled_segments_count
        except Exception:
            pass

        doc_ref.update(failure_update)

        record_event(job_id, "failed", failure_message, JobStatus.FAILED.value)

        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise

    finally:

        if local_path and os.path.exists(local_path):
            os.remove(local_path)
        if (
            processed_local_path
            and processed_local_path != local_path
            and processed_local_path != diarization_input_path
            and os.path.exists(processed_local_path)
        ):
            os.remove(processed_local_path)
        if diarization_input_path and os.path.exists(diarization_input_path):
            os.remove(diarization_input_path)


# ---------------------------------------------------------
# Worker Entry
# ---------------------------------------------------------
def process_next_job(worker_id: str, requested_job_id: Optional[str] = None):

    print(f"Worker {worker_id} checking queue...")

    job_id = (
        claim_specific_queued_job(requested_job_id)
        if requested_job_id
        else claim_one_queued_job()
    )

    if not job_id:
        return False

    asyncio.run(run_job(job_id))

    print("Worker finished.")

    return True


# ---------------------------------------------------------
# SRT
# ---------------------------------------------------------
def _segments_to_srt(segments: List[Dict[str, Any]]) -> str:

    lines = []
    idx = 1

    for s in segments:

        start = s.get("start")
        end = s.get("end")
        text = (s.get("text") or "").strip()
        speaker = s.get("speaker")

        if speaker and text:
            text = f"{speaker}: {text}"

        if start is None or end is None or not text:
            continue

        lines.append(str(idx))
        lines.append(
            f"{_format_srt_time(float(start))} --> {_format_srt_time(float(end))}"
        )
        lines.append(text)
        lines.append("")

        idx += 1

    return "\n".join(lines).strip() + "\n"


# ---------------------------------------------------------
# VTT
# ---------------------------------------------------------
def _segments_to_vtt(segments: List[Dict[str, Any]]) -> str:

    lines = ["WEBVTT", ""]

    for s in segments:

        start = s.get("start")
        end = s.get("end")
        text = (s.get("text") or "").strip()
        speaker = s.get("speaker")

        if speaker and text:
            text = f"{speaker}: {text}"

        if start is None or end is None or not text:
            continue

        lines.append(
            f"{_format_vtt_time(float(start))} --> {_format_vtt_time(float(end))}"
        )
        lines.append(text)
        lines.append("")

    return "\n".join(lines).strip() + "\n"


# ---------------------------------------------------------
# Podcast HTML Transcript
# ---------------------------------------------------------
def _build_podcast_html(
    job_id: str,
    segments: List[Dict[str, Any]],
    diarization: Optional[Dict[str, Any]] = None,
    language: Optional[str] = None,
) -> str:
    blocks = _build_transcript_blocks(segments)
    has_speaker_labels = _has_speaker_labels(segments)

    html = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "<meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>Transcript {escape(job_id)}</title>",
        "<style>",
        ":root {",
        "  color-scheme: light;",
        "  --page-bg: #f8fafc;",
        "  --page-grad-a: rgba(40, 41, 126, 0.12);",
        "  --page-grad-b: rgba(99, 102, 241, 0.08);",
        "  --panel: rgba(255, 255, 255, 0.94);",
        "  --panel-strong: #ffffff;",
        "  --text: #101426;",
        "  --muted: #667085;",
        "  --border: rgba(40, 41, 126, 0.12);",
        "  --accent: #28297e;",
        "  --accent-soft: rgba(99, 102, 241, 0.08);",
        "  --shadow: 0 18px 50px rgba(15, 23, 42, 0.08);",
        "}",
        "* { box-sizing: border-box; }",
        "body {",
        "  margin: 0;",
        "  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;",
        "  background:",
        "    radial-gradient(circle at top left, var(--page-grad-a) 0%, transparent 28%),",
        "    radial-gradient(circle at top right, var(--page-grad-b) 0%, transparent 24%),",
        "    linear-gradient(180deg, #ffffff 0%, var(--page-bg) 100%);",
        "  color: var(--text);",
        "}",
        ".page {",
        "  width: min(980px, calc(100% - 24px));",
        "  margin: 20px auto 40px;",
        "}",
        ".hero {",
        "  position: relative;",
        "  overflow: hidden;",
        "  background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(250,251,255,0.96));",
        "  border: 1px solid var(--border);",
        "  border-radius: 34px;",
        "  padding: 28px 24px 24px;",
        "  box-shadow: var(--shadow);",
        "}",
        ".hero::before {",
        "  content: '';",
        "  position: absolute;",
        "  inset: -40% auto auto 58%;",
        "  width: 260px;",
        "  height: 260px;",
        "  background: radial-gradient(circle, rgba(99,102,241,0.18) 0%, rgba(99,102,241,0) 72%);",
        "  pointer-events: none;",
        "}",
        ".eyebrow {",
        "  margin: 0 0 8px;",
        "  font-size: 0.78rem;",
        "  font-weight: 700;",
        "  line-height: 1.2;",
        "  letter-spacing: 0.18em;",
        "  text-transform: uppercase;",
        "  color: var(--accent);",
        "}",
        "h1 {",
        "  margin: 0;",
        "  max-width: 14ch;",
        "  font-size: clamp(2.2rem, 5vw, 4.4rem);",
        "  line-height: 0.94;",
        "  letter-spacing: -0.05em;",
        "  font-weight: 800;",
        "}",
        ".hero-copy {",
        "  position: relative;",
        "  z-index: 1;",
        "}",
        ".lede {",
        "  max-width: 640px;",
        "  margin: 14px 0 0;",
        "  color: var(--muted);",
        "  font-size: 1rem;",
        "  line-height: 1.75;",
        "}",
        ".meta-row {",
        "  display: flex;",
        "  flex-wrap: wrap;",
        "  gap: 10px;",
        "  margin-top: 18px;",
        "}",
        ".pill {",
        "  display: inline-flex;",
        "  align-items: center;",
        "  gap: 8px;",
        "  border-radius: 999px;",
        "  border: 1px solid rgba(40, 41, 126, 0.12);",
        "  background: rgba(240, 243, 255, 0.78);",
        "  padding: 10px 14px;",
        "  color: var(--accent);",
        "  font-size: 0.82rem;",
        "  font-weight: 700;",
        "  letter-spacing: 0.04em;",
        "}",
        ".transcript {",
        "  display: grid;",
        "  gap: 18px;",
        "  margin-top: 22px;",
        "}",
        ".block {",
        "  padding: 20px 20px 18px;",
        "  border: 1px solid var(--border);",
        "  border-radius: 28px;",
        "  background: var(--panel-strong);",
        "  box-shadow: var(--shadow);",
        "}",
        ".meta {",
        "  display: flex;",
        "  flex-wrap: wrap;",
        "  gap: 8px 12px;",
        "  align-items: baseline;",
        "  margin-bottom: 12px;",
        "}",
        ".speaker {",
        "  font-size: 0.86rem;",
        "  font-weight: 800;",
        "  line-height: 1.2;",
        "  letter-spacing: 0.14em;",
        "  text-transform: uppercase;",
        "  color: var(--accent);",
        "}",
        ".timestamp {",
        "  color: var(--muted);",
        "  font-size: 0.82rem;",
        "  font-weight: 600;",
        "  line-height: 1.2;",
        "}",
        ".block p {",
        "  margin: 0 0 14px;",
        "  font-size: 1.03rem;",
        "  line-height: 1.9;",
        "  color: #24304a;",
        "}",
        ".block p:last-child { margin-bottom: 0; }",
        "@media (max-width: 640px) {",
        "  .page { width: min(100% - 16px, 100%); margin: 12px auto 28px; }",
        "  .hero { padding: 22px 18px 18px; border-radius: 24px; }",
        "  h1 { max-width: 100%; font-size: 2.8rem; }",
        "  .block { padding: 16px; border-radius: 22px; }",
        "  .block p { font-size: 0.98rem; line-height: 1.8; }",
        "}",
        "</style>",
        "</head>",
        "<body>",
        "<main class='page'>",
        "<section class='hero'>",
        "<div class='hero-copy'>",
        "<p class='eyebrow'>Kreyai Transcript</p>",
        f"<h1>{'Speaker-Labeled Transcript' if has_speaker_labels else 'Transcript'}</h1>",
        "<p class='lede'>Structured, readable output designed for review, editing, and publishing without cleanup work.</p>",
        "<div class='meta-row'>",
        f"<span class='pill'>Job {escape(job_id)}</span>",
        f"<span class='pill'>{'Speaker labels included' if has_speaker_labels else 'Clean paragraph format'}</span>",
        "</div>",
        "</div>",
    ]

    html.extend([
        "</section>",
        "<section class='transcript'>",
    ])

    if has_speaker_labels:
        for spk, time_value, text in blocks:
            html.append("<article class='block'>")
            html.append(
                "<div class='meta'>"
                f"<span class='speaker'>{escape(str(spk))}</span>"
                f"<span class='timestamp'>{_format_hhmmss(float(time_value))}</span>"
                "</div>"
            )
            for paragraph in _split_transcript_paragraphs(text.strip()):
                html.append(f"<p>{escape(paragraph)}</p>")
            html.append("</article>")
    else:
        paragraph_text = _build_plain_paragraph_transcript(segments, language=language).strip()
        for paragraph in paragraph_text.split("\n\n") if paragraph_text else []:
            html.append("<article class='block'>")
            html.append(f"<p>{escape(paragraph)}</p>")
            html.append("</article>")

    html.extend([
        "</section>",
        "</main>",
        "</body>",
        "</html>",
    ])

    return "\n".join(html)


def _clean_ht_segments_for_output(segments: List[Dict[str, Any]], metadata: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    cleaned_segments: List[Dict[str, Any]] = []

    for segment in segments:
        cleaned_segment = dict(segment)
        cleaned_segment["text"] = run_ht_cleanup_pipeline(
            str(segment.get("text") or ""),
            metadata=metadata,
        )
        cleaned_segments.append(cleaned_segment)

    return cleaned_segments


# ---------------------------------------------------------
# Save Outputs
# ---------------------------------------------------------
def save_outputs(storage, job_id: str, result: Dict[str, Any]):
    text = (result.get("text") or "").strip()
    language = result.get("language")
    segments = _segments_from_result(result)
    if segments:
        transcript_text = (
            _build_transcript_text(segments, language=language)
            if _has_speaker_labels(segments)
            else _build_plain_paragraph_transcript(segments, language=language)
        )
    else:
        transcript_text = (apply_formatting(text, language=language) + "\n") if text else ""

    def build_docx_bytes(rendered_text: str) -> bytes:
        doc = Document()
        for block in rendered_text.strip().split("\n\n") if rendered_text.strip() else []:
            for line in block.split("\n"):
                doc.add_paragraph(line)

        buf = BytesIO()
        doc.save(buf)
        return buf.getvalue()

    storage.save_output(
        job_id,
        "transcript.txt",
        transcript_text.encode("utf-8"),
        "text/plain; charset=utf-8",
    )

    storage.save_output(
        job_id,
        "transcript.docx",
        build_docx_bytes(transcript_text),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    if language == "ht":
        if segments:
            cleaned_segments = _clean_ht_segments_for_output(segments, metadata=result.get("debug"))
            cleaned_transcript_text = (
                _build_transcript_text(cleaned_segments, language=language)
                if _has_speaker_labels(cleaned_segments)
                else _build_plain_paragraph_transcript(cleaned_segments, language=language)
            )
        else:
            cleaned_text = run_ht_cleanup_pipeline(text or transcript_text, metadata=result.get("debug"))
            cleaned_transcript_text = cleaned_text.strip() + "\n" if cleaned_text.strip() else ""

        storage.save_output(
            job_id,
            "transcript.raw.txt",
            transcript_text.encode("utf-8"),
            "text/plain; charset=utf-8",
        )
        storage.save_output(
            job_id,
            "transcript.raw.docx",
            build_docx_bytes(transcript_text),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        storage.save_output(
            job_id,
            "transcript.clean.txt",
            cleaned_transcript_text.encode("utf-8"),
            "text/plain; charset=utf-8",
        )
        storage.save_output(
            job_id,
            "transcript.clean.docx",
            build_docx_bytes(cleaned_transcript_text),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    speaker_segments = result.get("speaker_segments")
    if isinstance(speaker_segments, list):
        storage.save_output(
            job_id,
            "speaker_segments.json",
            (json.dumps(speaker_segments, indent=2) + "\n").encode("utf-8"),
            "application/json; charset=utf-8",
        )

    diarization = result.get("diarization")
    if isinstance(diarization, dict):
        storage.save_output(
            job_id,
            "diarization.json",
            (json.dumps(diarization, indent=2) + "\n").encode("utf-8"),
            "application/json; charset=utf-8",
        )

    if segments:

        srt = _segments_to_srt(segments)
        vtt = _segments_to_vtt(segments)
        html = _build_podcast_html(job_id, segments, diarization=diarization, language=language)

        storage.save_output(
            job_id,
            "transcript.srt",
            srt.encode("utf-8"),
            "application/x-subrip",
        )

        storage.save_output(
            job_id,
            "transcript.vtt",
            vtt.encode("utf-8"),
            "text/vtt; charset=utf-8",
        )

        storage.save_output(
            job_id,
            "transcript.html",
            html.encode("utf-8"),
            "text/html; charset=utf-8",
        )
