# =====================================
# FINAL TRANSCRIPT FORMATTING
# Linguistic + Structural formatting
# =====================================

import re
from typing import List, Dict


# ------------------------------------------------------------
# TEXT-ONLY FORMATTING (your original logic)
# ------------------------------------------------------------
def apply_formatting(text: str) -> str:
    """
    Final-stage linguistic formatting.
    Runs AFTER all correction layers.
    Safe, deterministic, and language-aware.
    """
    if not text:
        return text

    # 1. Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # 2. Punctuation spacing cleanup
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"([,.!?;:])([^\s])", r"\1 \2", text)

    # 3. Sentence capitalization
    def cap(match):
        return match.group(1) + match.group(2).upper()

    text = re.sub(r"(^|[.!?]\s+)([a-zà-ÿ])", cap, text)

    # 4. Haitian Creole–specific cleanup
    text = re.sub(r"\byo(?:\s+yo)+\b", "yo", text)

    # 5. Final whitespace polish
    text = re.sub(r"\s{2,}", " ", text)

    return text.strip()


# ------------------------------------------------------------
# SPEAKER STRUCTURE FORMATTING
# ------------------------------------------------------------
def format_speaker_transcript(
    segments: List[Dict],
    speaker_key: str = "speaker",
    text_key: str = "text",
) -> str:
    """
    Convert Whisper-like segments into clean speaker blocks.
    """

    if not segments:
        return ""

    blocks = []
    current_speaker = None
    buffer = []

    for seg in segments:
        speaker = seg.get(speaker_key, "Speaker 1")
        text = seg.get(text_key, "").strip()

        if not text:
            continue

        # Apply linguistic formatting per segment
        text = apply_formatting(text)

        if speaker != current_speaker:
            if buffer:
                blocks.append(
                    f"{current_speaker}:\n" + " ".join(buffer)
                )
                buffer = []

            current_speaker = speaker

        buffer.append(text)

    if buffer:
        blocks.append(
            f"{current_speaker}:\n" + " ".join(buffer)
        )

    return "\n\n".join(blocks)
