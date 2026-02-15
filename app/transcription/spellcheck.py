# app/transcription/spellcheck.py
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple, Set, Optional

from app.transcription.lexicon_store import load_lexicon

FEEDBACK_PATH = Path("app/storage/feedback.jsonl")

WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+(?:'[A-Za-zÀ-ÖØ-öø-ÿ]+)?", re.UNICODE)

# Things we never touch
TECH_SKIP_RE = re.compile(r"(^[A-Z0-9_-]+$)|(\d)|(_)|(-{2,})")
ENGLISHISH_SUFFIXES = ("tion", "ment", "ance", "ence", "able", "ible", "ous", "ing", "ed")


def _tokenize(text: str) -> List[Tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in WORD_RE.finditer(text)]


def _load_feedback_priors() -> Counter:
    """
    Builds a prior frequency for corrections:
      original -> corrected counts
    Only uses category in {"spell", "lexical", "technical"} by default,
    because those are the ones we want to reinforce for spelling.
    """
    priors = Counter()
    if not FEEDBACK_PATH.exists():
        return priors

    with FEEDBACK_PATH.open(encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            cat = (e.get("category") or "").lower()
            if cat not in {"spell", "lexical"}:
                continue
            o = (e.get("original") or "").strip().lower()
            c = (e.get("corrected") or "").strip().lower()
            if o and c and o != c:
                priors[(o, c)] += 1
    return priors


def _is_candidate_token(tok: str) -> bool:
    t = tok.strip()
    if len(t) < 3:
        return False

    # Skip technical / mixed tokens
    if TECH_SKIP_RE.search(t):
        return False

    # Skip ALLCAPS acronyms (EC2 / IAM etc)
    if t.isupper():
        return False

    # Skip obvious English-ish endings (very light heuristic)
    tl = t.lower()
    if any(tl.endswith(suf) for suf in ENGLISHISH_SUFFIXES):
        return False

    return True


def _edits1(word: str) -> Set[str]:
    """
    Classic edit-distance-1 generator (delete, transpose, replace, insert).
    Kept small: alphabet includes letters + apostrophe.
    """
    letters = "abcdefghijklmnopqrstuvwxyzàâäéèêëîïôöùûüç'"
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    deletes = [L + R[1:] for L, R in splits if R]
    transposes = [L + R[1] + R[0] + R[2:] for L, R in splits if len(R) > 1]
    replaces = [L + c + R[1:] for L, R in splits if R for c in letters]
    inserts = [L + c + R for L, R in splits for c in letters]
    return set(deletes + transposes + replaces + inserts)


def _edits2(word: str) -> Set[str]:
    # edit-distance 2 by applying edits1 twice (bounded by lexicon filter later)
    out = set()
    for e1 in _edits1(word):
        out |= _edits1(e1)
    return out


def _best_candidate(
    word: str,
    lexicon: Set[str],
    priors: Counter,
) -> Optional[Tuple[str, float, str]]:
    """
    Returns: (candidate, score, reason) or None.
    Score combines:
      - lexicon hit
      - feedback prior boost
    """
    w = word.lower()
    if w in lexicon:
        return None

    candidates = set()

    # Only generate distance-1 first (fast, safe)
    e1 = _edits1(w)
    c1 = [c for c in e1 if c in lexicon]
    candidates.update(c1)

    # If nothing, allow distance-2 but still lexicon-filtered
    if not candidates:
        e2 = _edits2(w)
        c2 = [c for c in e2 if c in lexicon]
        candidates.update(c2)

    if not candidates:
        return None

    # rank: prior count first, then shortest, then lexical order
    def rank_key(c: str):
        return (-priors[(w, c)], len(c), c)

    best = sorted(candidates, key=rank_key)[0]
    prior = priors[(w, best)]

    # score heuristic
    # base score: 0.70 for edit1 candidates, 0.55 for edit2 candidates
    base = 0.70 if best in c1 else 0.55
    score = base + min(0.25, 0.05 * prior)

    reason = f"spell:{w}→{best} prior={prior} base={base:.2f}"
    return best, score, reason


def apply_spellcheck(
    text: str,
    *,
    min_score: float = 0.75,
    max_changes: int = 20,
) -> Tuple[str, List[str]]:
    """
    Conservative spellcheck:
      - only changes tokens not in lexicon
      - only if candidate score >= min_score
      - logs changes
    """
    lexicon = load_lexicon()
    priors = _load_feedback_priors()

    tokens = _tokenize(text)
    if not tokens:
        return text, []

    chars = list(text)
    log: List[str] = []
    changes = 0
    offset = 0  # adjust spans after replacements

    for tok, start, end in tokens:
        if changes >= max_changes:
            break

        if not _is_candidate_token(tok):
            continue

        current_start = start + offset
        current_end = end + offset
        raw = "".join(chars[current_start:current_end])
        lw = raw.lower()

        if lw in lexicon:
            continue

        best = _best_candidate(raw, lexicon, priors)
        if not best:
            continue

        cand, score, reason = best
        if score < min_score:
            continue

        # Preserve capitalization style (simple)
        replacement = cand
        if raw[:1].isupper():
            replacement = cand[:1].upper() + cand[1:]

        # Apply replacement
        chars[current_start:current_end] = list(replacement)
        offset += len(replacement) - (current_end - current_start)

        log.append(f"{raw} → {replacement} ({reason}, score={score:.2f})")
        changes += 1

    return "".join(chars), log
