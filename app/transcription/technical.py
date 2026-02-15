# app/transcription/technical.py
from __future__ import annotations

import re
from typing import List, Tuple, Optional


# -------------------------------------------------------------------
# Policy
# -------------------------------------------------------------------

# If Whisper is confident (avg_logprob closer to 0),
# do NOT override technical terms
MIN_CONFIDENCE_TO_SKIP = -0.4


# -------------------------------------------------------------------
# Technical phrase lexicon
# Order matters: more specific patterns FIRST
# -------------------------------------------------------------------

TECH_RULES: List[Tuple[str, str]] = [
    # -----------------------
    # EC2
    # -----------------------
    (r"\bissitou\b", "EC2"),
    (
        r"\b(instance\s*mwen\s*yo|instans\s*mwen\s*yo|instantemoyo|instantimeo)\b",
        "instances mwen yo",
    ),

    # -----------------------
    # S3 (HIGH YIELD FIXES)
    # -----------------------
    # SS 3 / S S 3 / KS 3 / K S 3 / KS - 3
    (
        r"\b([sk]\s*[sk]?\s*[-]?\s*3)\b",
        "S3",
    ),

    # S3 to S3 variants
    (
        r"\b(s\s*3\s*(?:-|to|dash)\s*s\s*3)\b",
        "S3 to S3",
    ),

    # -----------------------
    # KMS / SSE
    # -----------------------
    (r"\bssi[-\s]*kms\b", "SSE-KMS"),

    # -----------------------
    # Encryption phrases
    # -----------------------
    (r"\bencryption\s*app\s*rest\b", "encryption at rest"),
    (r"\bencryption\s*(and|in)\s*transit\b", "encryption in transit"),
]


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------

def resolve_tech_phrases(
    text: str,
    confidence: Optional[float] = None,
) -> Tuple[str, List[str]]:
    """
    Resolve technical phrases ONLY when Whisper confidence is low.

    This function is:
    - deterministic
    - confidence-aware
    - token-safe
    - non-destructive

    Returns:
        (corrected_text, change_log)
    """

    if not text:
        return text, []

    # Skip if Whisper was confident
    if confidence is not None and confidence >= MIN_CONFIDENCE_TO_SKIP:
        return text, []

    out = text
    log: List[str] = []

    for pattern, replacement in TECH_RULES:
        new_out = re.sub(
            pattern,
            replacement,
            out,
            flags=re.IGNORECASE,
        )
        if new_out != out:
            log.append(f"TECH: {pattern} → {replacement}")
            out = new_out

    return out, log
