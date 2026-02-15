# app/transcription/lexicon_store.py
from __future__ import annotations

from pathlib import Path
from typing import Set

BASE_LEXICON_PATH = Path("app/storage/lexicon_base.txt")
LEARNED_LEXICON_PATH = Path("app/storage/lexicon_learned.txt")

BASE_LEXICON_PATH.parent.mkdir(parents=True, exist_ok=True)


def _read_words(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    words = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        w = line.strip()
        if not w or w.startswith("#"):
            continue
        words.add(w.lower())
    return words


def load_lexicon() -> Set[str]:
    """
    Combined lexicon: base + learned.
    """
    base = _read_words(BASE_LEXICON_PATH)
    learned = _read_words(LEARNED_LEXICON_PATH)
    return base | learned


def add_learned_word(word: str) -> None:
    w = word.strip().lower()
    if not w:
        return
    existing = _read_words(LEARNED_LEXICON_PATH)
    if w in existing:
        return
    LEARNED_LEXICON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEARNED_LEXICON_PATH.open("a", encoding="utf-8") as f:
        f.write(w + "\n")
