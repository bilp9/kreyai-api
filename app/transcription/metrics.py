import re
from typing import Optional

# -------------------------------------------------------------------
# Hallucination detection
# -------------------------------------------------------------------

_APOSTROPHE_RUN = re.compile(r"(?:\b\w'\s*){2,}")
_LOW_ALPHA = re.compile(r"[a-zA-Z]{2,}")


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
