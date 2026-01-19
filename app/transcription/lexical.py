import re
from typing import Tuple, List


# Fillers to remove when isolated or sentence-initial
FILLER_PATTERNS = [
    r"\b(euh+|uh+|um+|hmm+)\b",
    r"^(bon|alò|donk|donc)\b[, ]*",
    r"\b(you know|like)\b",
]

# Repeated word pattern (false starts)
REPEATED_WORD_PATTERN = r"\b(\w+)\s+\1\b"


def normalize_lexical_noise(text: str) -> Tuple[str, List[str]]:
    """
    A2 — Lexical cleanup
    Removes fillers, hesitations, and false-start repetitions
    """
    log = []
    original = text

    # Remove fillers
    for pattern in FILLER_PATTERNS:
        new_text = re.sub(pattern, "", text, flags=re.IGNORECASE)
        if new_text != text:
            log.append(f"removed filler: '{text}' → '{new_text.strip()}'")
            text = new_text

    # Collapse repeated words (false starts)
    while re.search(REPEATED_WORD_PATTERN, text):
        new_text = re.sub(REPEATED_WORD_PATTERN, r"\1", text)
        if new_text != text:
            log.append(f"collapsed repetition: '{text}' → '{new_text}'")
            text = new_text

    # Normalize whitespace
    new_text = re.sub(r"\s+", " ", text).strip()
    if new_text != text:
        log.append("normalized whitespace")
        text = new_text

    return text, log
