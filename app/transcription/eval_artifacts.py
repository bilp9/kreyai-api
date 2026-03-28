from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


EVAL_ROOT = Path("app/storage/evals")
_SAFE_CHARS_RE = re.compile(r"[^a-zA-Z0-9._-]+")
_WORD_RE = re.compile(r"\S+")


def _slug(value: Optional[str], *, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    cleaned = _SAFE_CHARS_RE.sub("-", raw).strip("-._")
    return cleaned or fallback


def _normalize_text(text: Optional[str]) -> str:
    return " ".join(str(text or "").split()).strip()


def _levenshtein(seq1: List[str], seq2: List[str]) -> int:
    if not seq1:
        return len(seq2)
    if not seq2:
        return len(seq1)

    prev = list(range(len(seq2) + 1))
    for i, left in enumerate(seq1, start=1):
        curr = [i]
        for j, right in enumerate(seq2, start=1):
            cost = 0 if left == right else 1
            curr.append(
                min(
                    prev[j] + 1,
                    curr[j - 1] + 1,
                    prev[j - 1] + cost,
                )
            )
        prev = curr
    return prev[-1]


def _word_tokens(text: str) -> List[str]:
    return _WORD_RE.findall(_normalize_text(text).lower())


def _char_tokens(text: str) -> List[str]:
    return list(_normalize_text(text).lower())


def _error_rate(reference: List[str], hypothesis: List[str]) -> Dict[str, Any]:
    edits = _levenshtein(reference, hypothesis)
    reference_count = len(reference)
    return {
        "edits": edits,
        "reference_count": reference_count,
        "error_rate": round(edits / max(1, reference_count), 4),
    }


def build_text_metrics(reference_text: Optional[str], hypothesis_text: str) -> Optional[Dict[str, Any]]:
    normalized_reference = _normalize_text(reference_text)
    if not normalized_reference:
        return None

    word_ref = _word_tokens(normalized_reference)
    word_hyp = _word_tokens(hypothesis_text)
    char_ref = _char_tokens(normalized_reference)
    char_hyp = _char_tokens(hypothesis_text)

    return {
        "reference_text": normalized_reference,
        "word_error_rate": _error_rate(word_ref, word_hyp),
        "character_error_rate": _error_rate(char_ref, char_hyp),
    }


def write_eval_artifact(
    *,
    audio_path: str,
    language_requested: str,
    language_detected: Optional[str],
    language_final: Optional[str],
    raw_segments: List[Dict[str, Any]],
    cleaned_segments: List[Dict[str, Any]],
    final_text: str,
    debug_payload: Optional[Dict[str, Any]],
    gold_text: Optional[str] = None,
    dataset_id: Optional[str] = None,
    run_label: Optional[str] = None,
    approved_for_improvement: bool = False,
) -> Path:
    timestamp = datetime.now(timezone.utc)
    dataset_slug = _slug(dataset_id, fallback="adhoc")
    run_slug = _slug(run_label, fallback=timestamp.strftime("%Y%m%dT%H%M%SZ"))

    output_dir = EVAL_ROOT / dataset_slug
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{run_slug}.json"
    payload = {
        "recorded_at": timestamp.isoformat(),
        "dataset_id": dataset_id or "adhoc",
        "run_label": run_label or run_slug,
        "approved_for_improvement": bool(approved_for_improvement),
        "audio_path": audio_path,
        "language_requested": language_requested,
        "language_detected": language_detected,
        "language_final": language_final,
        "raw_segments": raw_segments,
        "cleaned_segments": cleaned_segments,
        "final_text": final_text,
        "evaluation": build_text_metrics(gold_text, final_text),
        "debug": debug_payload,
    }

    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path
