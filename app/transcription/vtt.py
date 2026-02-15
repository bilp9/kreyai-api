# app/transcription/vtt.py
from typing import List


def _format_timestamp(seconds: float) -> str:
    """
    Convert seconds to WebVTT timestamp format:
    HH:MM:SS.mmm
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60

    return f"{hours:02}:{minutes:02}:{secs:06.3f}"


def build_vtt(segments: List[dict]) -> str:
    """
    Build WebVTT file content from Whisper segments.

    Each segment expected format:
    {
        "start": float,
        "end": float,
        "text": str,
        "speaker": optional str
    }
    """

    lines = ["WEBVTT\n"]

    for seg in segments:
        start = _format_timestamp(seg["start"])
        end = _format_timestamp(seg["end"])
        text = seg["text"].strip()

        speaker = seg.get("speaker")
        if speaker:
            text = f"{speaker}: {text}"

        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")

    return "\n".join(lines)
