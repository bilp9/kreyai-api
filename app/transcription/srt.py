# app/transcription/srt.py
from typing import List


def _format_timestamp(seconds: float) -> str:
    """
    Convert seconds to SRT timestamp:
    HH:MM:SS,mmm
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60

    return f"{hours:02}:{minutes:02}:{secs:06.3f}".replace(".", ",")


def build_srt(segments: List[dict]) -> str:
    """
    Build SRT content from Whisper segments.
    """

    lines = []

    for i, seg in enumerate(segments, start=1):
        start = _format_timestamp(seg["start"])
        end = _format_timestamp(seg["end"])
        text = seg["text"].strip()

        speaker = seg.get("speaker")
        if speaker:
            text = f"{speaker}: {text}"

        lines.append(str(i))
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")

    return "\n".join(lines)
