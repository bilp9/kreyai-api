# app/transcription/lexical.py
from __future__ import annotations

from app.transcription.dictionary_loader import load_dictionary
from typing import Dict, List, Tuple
import re


# -------------------------------------------------------------------
# High-confidence lexical corrections only
# ❗ No grammar logic here — just word-level fixes
# -------------------------------------------------------------------
LEXICAL_MAP: Dict[str, str] = {
    # discourse / fillers
    r"\bhan\b": "ann",
    r"\bpar le\b": "pale",
    r"\bklè\b": "klè",

    # time / numbers
    r"\bjodia\b": "jodi a",
    r"\bhe\b": "è",
    r"\bkektan\b": "kèk tan",

    # common nouns
    r"\bbagai\b": "bagay",
    r"\bapplication\b": "aplikasyon",
    r"\btechnologie\b": "teknoloji",
    r"\bblackout\b": "blackout",

    # verbs / expressions
    r"\bditet\b": "di tèt",
    r"\bmwen ditet mwen\b": "mwen di tèt mwen",
    r"\bcheke\b": "tcheke",
    r"\bman dem\b": "mande",
    r"\brepon\b": "reponn",

    # places / structures
    r"\blakai\b": "lakay",
    r"\blakala\b": "lakay la",

    # tech terms (keep English but normalize)
    r"\bencryption app rest\b": "encryption at rest",
    r"\bencryption and transit\b": "encryption in transit",
}


def apply_lexical_bias(text: str) -> Tuple[str, List[str]]:
    """
    Apply deterministic lexical corrections.
    Returns (corrected_text, change_log)
    """
    log: List[str] = []
    out = text

    # ---------------------------------------------------------------
    # 1. Rule-based lexical normalization (highest confidence)
    # ---------------------------------------------------------------
    for pattern, replacement in LEXICAL_MAP.items():
        new = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
        if new != out:
            log.append(f"{pattern} → {replacement}")
            out = new

    # ---------------------------------------------------------------
    # 2. Dictionary-backed normalization (data-driven)
    # ---------------------------------------------------------------
    dictionary = load_dictionary()

    for raw, entry in dictionary.items():
        normalized = entry.get("normalized")
        if not normalized:
            continue

        pattern = rf"\b{re.escape(raw)}\b"
        if re.search(pattern, out, flags=re.IGNORECASE):
            out = re.sub(pattern, normalized, out, flags=re.IGNORECASE)
            log.append(f"{raw} → {normalized} (dict)")

    # ---------------------------------------------------------------
    # 3. Whitespace normalization (final cleanup)
    # ---------------------------------------------------------------
    out = re.sub(r"\s+", " ", out).strip()

    return out, log
