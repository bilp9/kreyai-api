# app/transcription/verb_phrases.py
from __future__ import annotations

import re
from typing import List, Tuple

# -------------------------------------------------
# Regex patterns
# -------------------------------------------------

BAD_ORDER_RE = re.compile(
    r"\b(ap)\s+(pral)\b|\b(pral)\s+(ap)\b",
    flags=re.IGNORECASE,
)

DOUBLE_AUX_RE = re.compile(
    r"\b(ap|pral)\s+(a)\b|\b(a)\s+(ap|pral)\b",
    flags=re.IGNORECASE,
)

# -------------------------------------------------
# Public API
# -------------------------------------------------

def normalize_verb_phrases(text: str) -> Tuple[str, List[str]]:
    """
    Normalize Creole verb phrase structure.
    Returns normalized text + log of fixes.
    """
    changes: List[str] = []

    # Fix wrong ordering: pral ap → ap pral
    def _fix_order(match):
        original = match.group(0)
        fixed = "ap pral"
        changes.append(f"{original} → {fixed}")
        return fixed

    text = BAD_ORDER_RE.sub(_fix_order, text)

    # Remove weak/duplicate auxiliaries
    def _fix_double(match):
        original = match.group(0)
        kept = match.group(1) or match.group(3)
        changes.append(f"{original} → {kept}")
        return kept

    text = DOUBLE_AUX_RE.sub(_fix_double, text)

    return text, changes
