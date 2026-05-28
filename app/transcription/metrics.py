import re
from typing import Optional

# -------------------------------------------------------------------
# Hallucination detection
# -------------------------------------------------------------------

_APOSTROPHE_RUN = re.compile(r"(?:\b\w'\s*){2,}")
_LOW_ALPHA = re.compile(r"[a-zA-Z]{2,}")
_KNOWN_SUBTITLE_HALLUCINATIONS = (
    "sous-titrage société radio-canada",
    "sous titrage société radio-canada",
    "sous-titrage radio-canada",
    "sous titrage radio-canada",
)


def is_known_subtitle_hallucination(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "").casefold()).strip()
    return any(phrase in normalized for phrase in _KNOWN_SUBTITLE_HALLUCINATIONS)


def is_hallucinated(text: str) -> bool:
    t = text.strip()

    # Empty or tiny fragments
    if len(t) < 6:
        return True

    # Too many apostrophes (phoneme noise)
    if t.count("'") >= 3:
        return True

    # Repeated phoneme-like patterns
    if _APOSTROPHE_RUN.search(t):
        return True

    if is_known_subtitle_hallucination(t):
        return True

    # Not enough real letters
    if not _LOW_ALPHA.search(t):
        return True

    return False


# -------------------------------------------------------------------
# Correction telemetry (engine-facing, non-user)
# -------------------------------------------------------------------

def record_correction(
    *,
    token: str,
    replacement: str,
    confidence: Optional[float],
    rule: str,
    module: str,
    applied: bool,
) -> None:
    """
    Records correction rule evaluation.

    Telemetry only. Safe no-op for now.
    """
    return
