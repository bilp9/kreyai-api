# app/transcription/learn_from_feedback.py
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Tuple

from app.transcription.lexicon_store import (
    load_lexicon,
    add_learned_word,
)

FEEDBACK_PATH = Path("app/storage/feedback.jsonl")

MIN_PROMOTION_COUNT = 3   # ← tune this later
MAX_WORD_LENGTH = 32

WORD_RE = re.compile(r"^[a-zàâäéèêëîïôöùûüç']+$", re.IGNORECASE)
TECH_RE = re.compile(r"\d|[_\-]|^[A-Z]{2,}$")


def _is_safe_word(word: str) -> bool:
    w = word.strip()
    if not w:
        return False
    if len(w) > MAX_WORD_LENGTH:
        return False
    if TECH_RE.search(w):
        return False
    if not WORD_RE.match(w):
        return False
    return True


def promote_from_feedback(
    *,
    min_count: int = MIN_PROMOTION_COUNT,
    dry_run: bool = True,
) -> Dict[str, int]:
    """
    Reads feedback.jsonl and promotes stable corrected spellings
    into lexicon_learned.txt.

    Returns dict of promoted_word -> count
    """
    if not FEEDBACK_PATH.exists():
        print("No feedback file found.")
        return {}

    lexicon = load_lexicon()
    counts: Counter[str] = Counter()

    with FEEDBACK_PATH.open(encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue

            category = (e.get("category") or "").lower()
            if category not in {"spell", "lexical"}:
                continue

            original = (e.get("original") or "").strip().lower()
            corrected = (e.get("corrected") or "").strip().lower()

            if not original or not corrected:
                continue
            if original == corrected:
                continue

            # safety checks
            if not _is_safe_word(corrected):
                continue

            # already known → skip
            if corrected in lexicon:
                continue

            counts[corrected] += 1

    promoted = {
        word: cnt
        for word, cnt in counts.items()
        if cnt >= min_count
    }

    if not promoted:
        print("No words eligible for promotion.")
        return {}

    print("Eligible promotions:")
    for w, c in sorted(promoted.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {w}  (count={c})")

    if dry_run:
        print("\nDRY RUN — nothing written.")
        return promoted

    for word in promoted:
        add_learned_word(word)

    print(f"\nPromoted {len(promoted)} words into lexicon_learned.txt")
    return promoted


if __name__ == "__main__":
    promote_from_feedback(dry_run=True)
