import re
from typing import Tuple, List


VERB_NORMALIZATION_RULES = [
    # Normalize spacing around "ap"
    (r"\b(m|w|l|n|y|li|nou|yo)\s*ap\s+", r"\1 ap "),
    
    # Normalize spacing around "pral"
    (r"\b(m|w|l|n|y|li|nou|yo)\s*a\s*pral\s+", r"\1 a pral "),
]


def normalize_verb_phrases(text: str) -> Tuple[str, List[str]]:
    """
    A4 — Verb phrase normalization
    - Normalizes spacing for ap / pral constructions
    - Does NOT change tense or meaning
    """
    log = []
    original = text

    for pattern, replacement in VERB_NORMALIZATION_RULES:
        new_text = re.sub(pattern, replacement, text)
        if new_text != text:
            log.append(f"verb phrase normalized: '{text}' → '{new_text}'")
            text = new_text

    return text, log
