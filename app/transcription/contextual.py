# app/transcription/contextual.py
import re
from typing import List, Tuple

WINDOW_RULES = [
    {
        "pattern": r"\binstant\b",
        "block": True,
        "reason": "French word, not Creole",
    },
    {
        "pattern": r"\bpar le\b",
        "replacement": "pale",
        "confidence": 0.6,
    },
    {
        "pattern": r"\bapmach[eé]\b",
        "replacement": "ap mache",
        "confidence": 0.7,
    },
]

def apply_contextual_corrections(
    text: str,
    confidence: float = 1.0,
) -> Tuple[str, List[str]]:
    """
    Context-aware, confidence-gated corrections.
    """
    log = []
    out = text

    for rule in WINDOW_RULES:
        if re.search(rule["pattern"], out):
            # hard block (do nothing)
            if rule.get("block"):
                log.append(f"BLOCKED: {rule['pattern']} ({rule['reason']})")
                continue

            # confidence gate
            if confidence < rule.get("confidence", 0):
                continue

            out = re.sub(rule["pattern"], rule["replacement"], out)
            log.append(
                f"{rule['pattern']} → {rule['replacement']} (conf ≥ {rule['confidence']})"
            )

    return out, log
