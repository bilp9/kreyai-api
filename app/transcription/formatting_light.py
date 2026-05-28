from __future__ import annotations

import re
from typing import List


HT_SAFE_TOKEN_FIXES = {
    "nanpam": "non pa m",
    "nonpam": "non pa m",
    "npral": "n pral",
    "mwe": "mwen",
    "yong": "yon",
    "jodiya": "jodi a",
    "jodia": "jodi a",
    "seyon": "se yon",
    "napfe": "n ap fe",
    "mwenken": "mwen gen",
    "poujwen": "pou jwenn",
}

SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+")
HT_READABILITY_MARKERS = (
    "Bonjour ekip",
    "Bonjou ekip",
    "Non pa m se",
    "Mwen gen",
    "Donk",
    "Epi",
    "Bon",
    "Mersi",
)
HT_READABILITY_MARKER_RE = re.compile(
    r"\s+("
    + "|".join(re.escape(marker).replace(r"\ ", r"\s+") for marker in HT_READABILITY_MARKERS)
    + r")\b",
    flags=re.IGNORECASE,
)


def _cleanup_punctuation_spacing(text: str) -> str:
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"([,.!?;:])([^\s\"')\]}])", r"\1 \2", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _apply_case_style(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper() and source[1:].islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _apply_safe_token_fixes(text: str) -> str:
    for wrong, correct in HT_SAFE_TOKEN_FIXES.items():
        pattern = rf"\b{re.escape(wrong)}\b"

        def repl(match: re.Match[str]) -> str:
            return _apply_case_style(match.group(0), correct)

        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)

    text = re.sub(r"\bm'ap\b", "m ap", text, flags=re.IGNORECASE)
    text = re.sub(r"\bn'ap\b", "n ap", text, flags=re.IGNORECASE)
    text = re.sub(r"\bk'ap\b", "k ap", text, flags=re.IGNORECASE)
    text = re.sub(r"\bt'ap\b", "t ap", text, flags=re.IGNORECASE)
    return text


def _chars_since_sentence_break(text: str) -> int:
    last_break = max(text.rfind("."), text.rfind("!"), text.rfind("?"), text.rfind("\n"))
    return len(text) if last_break < 0 else len(text) - last_break - 1


def _add_ht_readability_punctuation(text: str) -> str:
    """Add conservative sentence breaks without changing spoken words."""

    def repl(match: re.Match[str]) -> str:
        prefix = text[: match.start()].rstrip()
        if not prefix:
            return match.group(0)
        if prefix.endswith((".", "!", "?", ":", ";")):
            return " " + match.group(1)
        if _chars_since_sentence_break(prefix) < 48:
            return match.group(0)
        return ". " + match.group(1)

    return HT_READABILITY_MARKER_RE.sub(repl, text)


def split_into_light_paragraphs(
    text: str,
    *,
    target_sentences: int = 3,
    max_sentences: int = 5,
    max_chars: int = 520,
) -> List[str]:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return []

    sentences = [part.strip() for part in SENTENCE_BREAK_RE.split(normalized) if part.strip()]
    if not sentences:
        return [normalized]

    paragraphs: List[str] = []
    current: List[str] = []

    for sentence in sentences:
        current.append(sentence)
        current_text = " ".join(current).strip()
        if (
            len(current) >= max_sentences
            or len(current_text) >= max_chars
            or (len(current) >= target_sentences and re.search(r"[.!?]$", sentence))
        ):
            paragraphs.append(" ".join(current).strip())
            current = []

    if current:
        paragraphs.append(" ".join(current).strip())

    return paragraphs


def apply_light_formatting(text: str, *, language: str | None = None) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return ""

    if language == "ht":
        normalized = _apply_safe_token_fixes(normalized)
        normalized = _add_ht_readability_punctuation(normalized)

    normalized = _cleanup_punctuation_spacing(normalized)
    return normalized


def minimal_postprocess_ht(text: str) -> str:
    normalized = apply_light_formatting(text, language="ht")
    paragraphs = split_into_light_paragraphs(normalized)
    if not paragraphs:
        return normalized
    return "\n\n".join(paragraphs).strip()
