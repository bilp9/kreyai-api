# app/transcription/ht_density.py
from __future__ import annotations
import re
from typing import Dict, List

# ------------------------------------------------------------------
# Lexicons (VERY small by design)
# ------------------------------------------------------------------

HT_CORE = {
    "mwen", "ou", "li", "nou", "yo",
    "pa", "ap", "te", "pral",
    "se", "sa", "sa a", "sa yo",
    "ki", "ke", "kote",
    "nan", "sou", "ak",
    "pou", "avèk",
    "gen", "fè", "di", "ale", "vini"
}

HT_WEAK = {
    "bon", "byen", "men", "paske",
    "tankou", "lè", "toujou",
    "ankò", "deja", "menm"
}

NON_HT_MARKERS = {
    "the", "and", "with", "for", "that",
    "mais", "avec", "pour", "est", "être"
}

_TOKEN_RE = re.compile(r"[a-zàâèéêëîïôùûüç']+")


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


# ------------------------------------------------------------------
# Windowed HT density scorer
# ------------------------------------------------------------------

def compute_ht_density_window(
    text: str,
    window: int = 12,
    stride: int = 6,
) -> Dict[str, float]:
    """
    Computes HT density over sliding windows.
    Returns the MAX density observed (decisive).
    """

    tokens = _tokenize(text)
    if not tokens:
        return {
            "ht_density": 0.0,
            "core_hits": 0,
            "weak_hits": 0,
            "non_ht_hits": 0,
            "token_count": 0,
        }

    max_density = 0.0
    best = (0, 0, 0, 0)

    for i in range(0, len(tokens), stride):
        window_tokens = tokens[i : i + window]
        if not window_tokens:
            continue

        core = sum(1 for t in window_tokens if t in HT_CORE)
        weak = sum(1 for t in window_tokens if t in HT_WEAK)
        non_ht = sum(1 for t in window_tokens if t in NON_HT_MARKERS)

        score = (core + 0.5 * weak - 0.5 * non_ht) / len(window_tokens)

        if score > max_density:
            max_density = score
            best = (core, weak, non_ht, len(window_tokens))

    core, weak, non_ht, count = best

    return {
        "ht_density": round(max_density, 3),
        "core_hits": core,
        "weak_hits": weak,
        "non_ht_hits": non_ht,
        "token_count": count,
    }
def compute_ht_density(text: str) -> dict:
    """
    Single-segment HT density.
    Thin wrapper around windowed version for engine compatibility.
    """
    return compute_ht_density_window(text)
# -------------------------------------------------
# A3 gating policy
# -------------------------------------------------

def should_fire_a3(
    metrics: dict,
    *,
    min_density: float = 0.25,
    min_core_hits: int = 2,
) -> bool:
    """
    Decide whether A3 (phonetic/grammar normalization)
    is allowed to run on this segment/window.

    Conservative by default.
    """

    if not metrics:
        return False

    ht_density = metrics.get("ht_density", 0.0)
    core_hits = metrics.get("core_hits", 0)

    # Hard gate: insufficient Creole signal
    if ht_density < min_density:
        return False

    # Hard gate: not enough core HT tokens
    if core_hits < min_core_hits:
        return False

    return True
