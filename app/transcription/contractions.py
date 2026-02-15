# app/transcription/contractions.py
from __future__ import annotations

import re
from typing import List, Tuple

# -------------------------------------------------
# Supported contraction prefixes
# -------------------------------------------------

SUBJECT_PREFIXES = {"m", "w", "l", "n", "y"}
AUXILIARIES = {"ap", "te", "a", "ta", "pral"}

# -------------------------------------------------
# Regex
# -------------------------------------------------

# Examples matched:
#   m'ap, m’ ap, m’te, w’a, l’pral
CONTRACTION_RE = re.compile(
    r"\b([mwlny])\s*[’']\s*(ap|te|a|ta|pral)\b",
    flags=re.IGNORECASE,
)

# -------------------------------------------------
# Public API
# -------------------------------------------------

def expand_contractions(text: str) -> Tuple[str, List[str]]:
    """
    Expand Creole contractions:
      m'ap  -> m ap
      w’te  -> w te

    Returns:
      expanded_text,
      list of expansions performed
    """
    expansions: List[str] = []

    def _replace(match):
        subject = match.group(1)
        aux = match.group(2)
        original = match.group(0)
        expanded = f"{subject} {aux}"

        expansions.append(f"{original} → {expanded}")
        return expanded

    expanded_text = CONTRACTION_RE.sub(_replace, text)
    return expanded_text, expansions
