from __future__ import annotations

import re
from typing import List, Tuple

# -------------------------------------------------
# Dialect normalization rules (A5)
# -------------------------------------------------

DIALECT_RULES = [
    # n ap → nap
    (re.compile(r"\bn\s+ap\b", re.IGNORECASE), "nap"),

    # m a pral → m a pral (spacing normalization)
    (re.compile(r"\b(m|n|l|li|nou|yo)\s+a\s+pral\b", re.IGNORECASE), r"\1 a pral"),

    # m a → m a (spacing normalization)
    (re.compile(r"\b(m|n|l|li|nou|yo)\s+a\b", re.IGNORECASE), r"\1 a"),
]


def normalize_dialect_variants(text: str) -> Tuple[str, List[str]]:
    """
    Normalize dialectal surface variants without changing meaning.
    Returns (normalized_text, change_log)
    """
    changes: List[str] = []

    for pattern, replacement in DIALECT_RULES:
        def _apply(match):
            original = match.group(0)
            fixed = pattern.sub(replacement, original)
            if original != fixed:
                changes.append(f"{original} → {fixed}")
            return fixed

        text = pattern.sub(_apply, text)

    return text, changes
