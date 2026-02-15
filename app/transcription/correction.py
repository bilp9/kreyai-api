# app/transcription/correction.py
from __future__ import annotations

from typing import Callable, List, Tuple, Optional, Dict
import re

# Token correction function:
# returns:
#   fixed_text,
#   log_messages
CorrectionFn = Callable[[str, Optional[float]], Tuple[str, List[str]]]

_WS_RE = re.compile(r"\s+")


def _tokenize(text: str) -> List[str]:
    # Keep punctuation attached (resolver may rely on it)
    return [t for t in _WS_RE.split(text.strip()) if t]


def _detokenize(tokens: List[str]) -> str:
    return " ".join(tokens).strip()


def apply_token_level_correction(
    text: str,
    correction_fn: CorrectionFn,
    confidence: Optional[float] = None,
) -> Tuple[str, List[str]]:
    """
    Non-destructive token-level correction.
    Always returns the full text (same token count unless correction_fn changes it).
    """
    if not text:
        return "", []

    tokens = _tokenize(text)
    out_tokens: List[str] = []
    log: List[str] = []

    for tok in tokens:
        fixed_tok, tok_log = correction_fn(tok, confidence)
        out_tokens.append(fixed_tok)
        if tok_log:
            log.extend(tok_log)

    return _detokenize(out_tokens), log


def apply_token_level_correction_low_conf_only(
    segments: List[Dict],
    correction_fn: CorrectionFn,
) -> Tuple[str, List[str]]:
    """
    Applies correction_fn ONLY to segments where seg['low_confidence'] is True.
    For all other segments, text is preserved exactly.

    Returns:
      final_text (all segments joined with spaces),
      log (aggregated)
    """
    out_texts: List[str] = []
    log: List[str] = []

    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue

        low_conf = bool(seg.get("low_confidence", False))
        conf = seg.get("avg_logprob", None)

        if not low_conf:
            # preserve segment as-is
            out_texts.append(text)
            continue

        fixed, seg_log = apply_token_level_correction(
            text=text,
            correction_fn=correction_fn,
            confidence=conf,
        )
        out_texts.append(fixed)
        log.extend(seg_log)

    return " ".join(out_texts).strip(), log


# Backwards-compatible alias (so engine imports don't break)
apply_confidence_weighted_correction = apply_token_level_correction_low_conf_only
