from __future__ import annotations

import json
import subprocess
import asyncio
import os
from datetime import datetime
import time
from html import escape
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

from app.transcription.engine import transcribe_audio, normalize_language_code
from app.transcription.diarization import (
    diarize_audio,
    get_diarization_configuration_error,
)
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


def _build_transcript_text(segments: List[Dict[str, Any]]) -> str:

    lines: List[str] = []

    for speaker, time_value, text in _build_transcript_blocks(segments):
        lines.append(f"{speaker} ({_format_hhmmss(time_value)})")
        for paragraph in _split_transcript_paragraphs(text):
            lines.append(paragraph)
        lines.append("")

    return "\n".join(lines).strip() + "\n" if lines else ""


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


def cleanup_chunk_files(chunk_paths: List[str]) -> None:
    if not chunk_paths:
        return

    for path in chunk_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    chunk_dir = os.path.dirname(chunk_paths[0])
    try:
        if os.path.isdir(chunk_dir) and not os.listdir(chunk_dir):
            os.rmdir(chunk_dir)
    except Exception:
        pass


def merge_chunk_results(chunk_results: List[Dict[str, Any]], chunk_durations: List[float]) -> Dict[str, Any]:

    merged_segments: List[Dict[str, Any]] = []
    merged_text_parts: List[str] = []

    offset = 0.0

    for result, duration in zip(chunk_results, chunk_durations):

        chunk_text = (result.get("text") or "").strip()
        if chunk_text:
            merged_text_parts.append(chunk_text)

        for seg in _segments_from_result(result):
            merged_words = []
            for word in seg.get("words") or []:
                if not isinstance(word, dict):
                    continue

                word_start = word.get("start")
                word_end = word.get("end")

                merged_words.append(
                    {
                        **word,
                        "start": (
                            float(word_start) + offset
                            if word_start is not None
                            else None
                        ),
                        "end": (
                            float(word_end) + offset
                            if word_end is not None
                            else None
                        ),
                    }
                )

            merged_segments.append(
                {
                    "start": float(seg.get("start", 0.0)) + offset,
                    "end": float(seg.get("end", 0.0)) + offset,
                    "text": (seg.get("text") or "").strip(),
                    "words": merged_words,
                }
            )

        offset += duration

    return {
        "text": " ".join(merged_text_parts).strip(),
        "segments": merged_segments,
    }


async def transcribe_with_optional_chunking(file_path: str, language: str) -> Dict[str, Any]:

    total_duration = get_audio_duration_seconds(file_path)

    if total_duration <= CHUNK_IF_LONGER_THAN_SECONDS:
        return await asyncio.to_thread(
            transcribe_audio,
            file_path,
            language=language,
        )

    print(
        f"Audio exceeds {CHUNK_IF_LONGER_THAN_SECONDS}s; "
        f"chunking into {CHUNK_SIZE_SECONDS}s segments"
    )

    chunk_paths = split_audio_into_chunks(file_path, CHUNK_SIZE_SECONDS)

    try:

        chunk_results: List[Dict[str, Any]] = []
        chunk_durations: List[float] = []

        for chunk_path in chunk_paths:

            duration = get_audio_duration_seconds(chunk_path)
            chunk_durations.append(duration)

            result = await asyncio.to_thread(
                transcribe_audio,
                chunk_path,
                language=language,
            )

            chunk_results.append(result)

        return merge_chunk_results(chunk_results, chunk_durations)

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

        if not source_blob:
            raise RuntimeError("Job missing storage path")

        download_start_time = time.time()
        storage.download_to_file(source_blob, local_path)
        download_time_seconds = round(time.time() - download_start_time, 3)

        # ---------------------------------------------------------
        # Run speaker diarization before transcription
        # ---------------------------------------------------------
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
                speaker_segments = await asyncio.to_thread(
                    diarize_audio,
                    local_path
                )
                diarization_time_seconds = round(time.time() - diarization_start_time, 3)
                print(f"Diarization segments detected: {len(speaker_segments)}")
                diarization_status = (
                    "completed" if speaker_segments else "completed_empty"
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

        transcription_start_time = time.time()
        result = await asyncio.wait_for(
            transcribe_with_optional_chunking(
                local_path,
                language=requested_language,
            ),
            timeout=PROCESS_ATTEMPT_TIMEOUT_SECONDS,
        )
        transcription_time_seconds = round(time.time() - transcription_start_time, 3)

        alignment_start_time = time.time()
        align_speakers(result, speaker_segments)
        alignment_time_seconds = round(time.time() - alignment_start_time, 3)
        result["speaker_segments"] = speaker_segments
        result["diarization"] = {
            "status": diarization_status,
            "error": diarization_error_message,
        }
        labeled_segments_count = _count_speaker_labeled_segments(result)

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
                "language_final": requested_language,
                "diarization_status": diarization_status,
                "diarization_error": diarization_error_message,
                "diarization_segments_count": len(speaker_segments),
                "speaker_labeled_segments_count": labeled_segments_count,
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
) -> str:
    blocks = _build_transcript_blocks(segments)

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
        "  --bg: #f6efe2;",
        "  --panel: #fffdf9;",
        "  --text: #1f1a17;",
        "  --muted: #6f655c;",
        "  --border: #e8dccd;",
        "  --accent: #b25b2a;",
        "  --accent-soft: #f6e5d8;",
        "}",
        "* { box-sizing: border-box; }",
        "body {",
        "  margin: 0;",
        "  font-family: Georgia, 'Times New Roman', serif;",
        "  background:",
        "    radial-gradient(circle at top, #fff8ef 0%, var(--bg) 58%, #eadcca 100%);",
        "  color: var(--text);",
        "}",
        ".page {",
        "  width: min(900px, calc(100% - 24px));",
        "  margin: 24px auto 48px;",
        "}",
        ".hero {",
        "  background: linear-gradient(135deg, rgba(178, 91, 42, 0.10), rgba(255, 255, 255, 0.92));",
        "  border: 1px solid var(--border);",
        "  border-radius: 24px;",
        "  padding: 24px 22px;",
        "  box-shadow: 0 14px 40px rgba(78, 54, 31, 0.08);",
        "}",
        ".eyebrow {",
        "  margin: 0 0 8px;",
        "  font: 600 0.78rem/1.2 Arial, sans-serif;",
        "  letter-spacing: 0.14em;",
        "  text-transform: uppercase;",
        "  color: var(--accent);",
        "}",
        "h1 {",
        "  margin: 0;",
        "  font-size: clamp(2rem, 4vw, 3.2rem);",
        "  line-height: 0.96;",
        "}",
        ".subtitle {",
        "  margin: 12px 0 0;",
        "  color: var(--muted);",
        "  font: 400 1rem/1.6 Arial, sans-serif;",
        "}",
        ".note {",
        "  margin: 18px 0 0;",
        "  padding: 12px 14px;",
        "  border-left: 4px solid var(--accent);",
        "  border-radius: 12px;",
        "  background: var(--accent-soft);",
        "  color: #5c331b;",
        "  font: 400 0.95rem/1.5 Arial, sans-serif;",
        "}",
        ".transcript {",
        "  display: grid;",
        "  gap: 16px;",
        "  margin-top: 20px;",
        "}",
        ".block {",
        "  padding: 18px 18px 16px;",
        "  border: 1px solid var(--border);",
        "  border-radius: 20px;",
        "  background: rgba(255, 253, 249, 0.96);",
        "  box-shadow: 0 10px 26px rgba(78, 54, 31, 0.05);",
        "}",
        ".meta {",
        "  display: flex;",
        "  flex-wrap: wrap;",
        "  gap: 8px 12px;",
        "  align-items: baseline;",
        "  margin-bottom: 10px;",
        "}",
        ".speaker {",
        "  font: 700 0.96rem/1.2 Arial, sans-serif;",
        "  letter-spacing: 0.06em;",
        "  text-transform: uppercase;",
        "}",
        ".timestamp {",
        "  color: var(--muted);",
        "  font: 600 0.83rem/1.2 Arial, sans-serif;",
        "}",
        ".block p {",
        "  margin: 0 0 12px;",
        "  font-size: 1.18rem;",
        "  line-height: 1.72;",
        "}",
        ".block p:last-child { margin-bottom: 0; }",
        "@media (max-width: 640px) {",
        "  .page { width: min(100% - 16px, 100%); margin: 12px auto 28px; }",
        "  .hero { padding: 18px 16px; border-radius: 18px; }",
        "  .block { padding: 14px 14px 12px; border-radius: 16px; }",
        "  .block p { font-size: 1.04rem; line-height: 1.62; }",
        "}",
        "</style>",
        "</head>",
        "<body>",
        "<main class='page'>",
        "<section class='hero'>",
        "<p class='eyebrow'>Transcript Export</p>",
        "<h1>Podcast Transcript</h1>",
        f"<p class='subtitle'>Job {escape(job_id)}. Speaker-labeled transcript grouped into readable sections.</p>",
    ]

    diarization = diarization or {}
    diarization_status = str(diarization.get("status") or "").strip()
    diarization_error = str(diarization.get("error") or "").strip()

    if diarization_status and diarization_status != "completed":
        note = f"Speaker diarization unavailable ({diarization_status})."
        if diarization_error:
            note = f"{note} {diarization_error}"
        html.append(f"<p class='note'>{escape(note)}</p>")

    html.extend([
        "</section>",
        "<section class='transcript'>",
    ])

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

    html.extend([
        "</section>",
        "</main>",
        "</body>",
        "</html>",
    ])

    return "\n".join(html)


# ---------------------------------------------------------
# Save Outputs
# ---------------------------------------------------------
def save_outputs(storage, job_id: str, result: Dict[str, Any]):
    text = (result.get("text") or "").strip()
    segments = _segments_from_result(result)
    transcript_text = _build_transcript_text(segments) if segments else (text + "\n" if text else "")

    storage.save_output(
        job_id,
        "transcript.txt",
        transcript_text.encode("utf-8"),
        "text/plain; charset=utf-8",
    )

    doc = Document()

    for block in transcript_text.strip().split("\n\n") if transcript_text.strip() else []:
        for line in block.split("\n"):
            doc.add_paragraph(line)

    buf = BytesIO()
    doc.save(buf)

    storage.save_output(
        job_id,
        "transcript.docx",
        buf.getvalue(),
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
        html = _build_podcast_html(job_id, segments, diarization=diarization)

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
