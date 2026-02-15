# app/transcription/reversal.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional
import re


@dataclass(frozen=True)
class A3Event:
    """
    One A3 rule application event.
    Immutable + serializable.
    """
    rule_id: str
    before: str
    after: str
    mode: str                 # "restricted" | "full"
    speaker_id: Optional[str] = None
    segment_id: Optional[str] = None


_WS_RE = re.compile(r"\s+")


def _norm(s: str) -> str:
    """
    Conservative normalization:
    - lowercase
    - collapse whitespace
    We intentionally keep punctuation to avoid false positives.
    """
    return _WS_RE.sub(" ", (s or "").strip().lower())


def _contains(haystack: str, needle: str) -> bool:
    """
    Conservative substring check.
    """
    h = _norm(haystack)
    n = _norm(needle)
    if not n:
        return False
    return n in h


def detect_a3_reversals(
    *,
    a3_events: Iterable[A3Event],
    final_text: str,
) -> List[A3Event]:
    """
    Deterministic A3 reversal detection.

    A rule is considered reversed if:
      - A3 changed `before` → `after`
      - final_text CONTAINS `before`
      - final_text DOES NOT CONTAIN `after`

    This captures:
      - downstream undo
      - contradiction
      - rejection by later layers
    """
    reversed_events: List[A3Event] = []

    final_norm = _norm(final_text)

    for ev in a3_events:
        if not ev.before or not ev.after:
            continue

        # no-op rule, ignore
        if _norm(ev.before) == _norm(ev.after):
            continue

        after_present = _contains(final_norm, ev.after)
        before_present = _contains(final_norm, ev.before)

        if before_present and not after_present:
            reversed_events.append(ev)

    return reversed_events


def reversal_rate(
    *,
    a3_events: Iterable[A3Event],
    final_text: str,
) -> float:
    events = list(a3_events)
    if not events:
        return 0.0
    rev = detect_a3_reversals(a3_events=events, final_text=final_text)
    return len(rev) / max(1, len(events))
