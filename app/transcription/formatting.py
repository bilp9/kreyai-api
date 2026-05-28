# =====================================
# FINAL TRANSCRIPT FORMATTING
# Linguistic + Structural formatting
# =====================================

import difflib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from app.transcription.lexicon_store import load_learned_lexicon


SENTENCE_STARTERS = (
    "men",
    "epi",
    "ebyen",
    "alò",
    "donk",
    "konsa",
    "sepandan",
    "malgre sa",
    "anfen",
    "kounye a",
    "jodi a",
)

HT_TOKEN_FIXES = {
    "nanpam": "non pa m",
    "nonpam": "non pa m",
    "npral": "n pral",
    "mwe": "mwen",
    "mwenm": "mwen",
    "yong": "yon",
    "yons": "yon",
    "aveke": "avèk",
    "avek": "avèk",
    "avet": "avèk",
    "metin": "medsin",
    "realiti": "reyalite",
    "profesyonel": "pwofesyonèl",
    "pasyen": "pasyan",
    "genye": "genyen",
    "konen": "konnen",
    "ansam": "ansanm",
    "sate": "sante",
    "mersi": "mesi",
    "joudi": "jodi",
    "feke": "fèk",
    "meme": "menm",
    "sitwasyon": "sitiyasyon",
    "jodiya": "jodi a",
    "jodia": "jodi a",
    "jodiy": "jodi",
    "toumoun": "tout moun",
}

HT_AKADEMI_FIXES = {
    "lii": "li",
    "sakapfet": "sa k ap fèt",
    "nap": "n ap",
    "poutor": "pita",
}

HT_DO_NOT_TOUCH = {
    "amazon",
    "whatsapp",
    "social",
    "medicine",
    "podcast",
    "podcasts",
}
HT_WORD_RE = re.compile(r"\b[\wàâèéêëîïôòùûüç'-]+\b", re.UNICODE)


@lru_cache(maxsize=1)
def _load_ht_spelling_lexicon() -> frozenset[str]:
    path = Path("data/akademi/processed/lexicon.json")
    words = set()

    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            words.update(str(word).lower() for word in payload.keys())
        except Exception:
            pass

    words.update(word.lower() for word in load_learned_lexicon())
    words.update(part.lower() for value in HT_AKADEMI_FIXES.values() for part in value.split())
    words.update(part.lower() for value in HT_TOKEN_FIXES.values() for part in value.split())
    return frozenset(words)


def _cleanup_punctuation_spacing(text: str) -> str:
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"([,.!?;:])([^\s\"')\]}])", r"\1 \2", text)
    text = re.sub(r"\s+(['’])\s+", r"\1", text)
    return text


def _insert_natural_sentence_breaks(text: str) -> str:
    if not text:
        return text

    for starter in SENTENCE_STARTERS:
        pattern = rf"(?<![.!?])\s+({re.escape(starter)})\b"
        text = re.sub(pattern, r". \1", text, flags=re.IGNORECASE)

    text = re.sub(r"([a-zà-ÿ0-9])\s+(So|Yeah|Yes|No)\b", r"\1. \2", text)
    return text


def _normalize_terminal_punctuation(text: str) -> str:
    if not text:
        return text
    if re.search(r"[.!?]$", text):
        return text
    return text + "."


def _capitalize_sentences(text: str) -> str:
    def cap(match):
        return match.group(1) + match.group(2).upper()

    return re.sub(r"(^|[.!?]\s+)([a-zà-ÿ])", cap, text)


def _apply_case_style(source: str, replacement: str) -> str:
    if not source:
        return replacement
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper() and source[1:].islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _apply_ht_token_fixes(text: str) -> str:
    for wrong, correct in HT_TOKEN_FIXES.items():
        pattern = rf"\b{re.escape(wrong)}\b"

        def repl(match: re.Match[str]) -> str:
            return _apply_case_style(match.group(0), correct)

        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)

    text = re.sub(r"\bm'ap\b", "m ap", text, flags=re.IGNORECASE)
    text = re.sub(r"\bn'ap\b", "n ap", text, flags=re.IGNORECASE)
    text = re.sub(r"\bk'ap\b", "k ap", text, flags=re.IGNORECASE)
    text = re.sub(r"\bt'ap\b", "t ap", text, flags=re.IGNORECASE)
    return text


def _apply_ht_akademi_fixes(text: str) -> str:
    words = text.split()
    normalized: List[str] = []

    for word in words:
        clean_word = re.sub(r"[^\wàâèéêëîïôòùûüç'-]", "", word)
        lower_word = clean_word.lower()

        if lower_word in HT_DO_NOT_TOUCH:
            normalized.append(word)
        elif lower_word in HT_AKADEMI_FIXES:
            replacement = HT_AKADEMI_FIXES[lower_word]
            normalized.append(word.replace(clean_word, replacement))
        else:
            normalized.append(word)

    return " ".join(normalized)


def _apply_ht_spacing_repairs(text: str) -> str:
    repairs = (
        (r"\bsayo\b", "sa yo"),
        (r"\bkiap\b", "ki ap"),
        (r"\bsepa\b", "se pa"),
        (r"\bsanteya\b", "sante ya"),
        (r"\bmounyo\b", "moun yo"),
        (r"\bmpense\b", "m panse"),
        (r"\bmbap\b", "m ap"),
        (r"\bkapap\b", "ka kapab"),
    )

    for pattern, replacement in repairs:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    return text


def _apply_ht_phrase_repairs(text: str) -> str:
    repairs = (
        (
            r"\bmwen kontan avèk\.?\s+nou[,.]?\s+avèk\b",
            "mwen kontan avèk nou, avèk",
        ),
        (
            r"\bpwofesyonèl sante\.?\s+yo avèk pasyan\.?\s+yo ap fe fas\b",
            "pwofesyonèl sante yo avèk pasyan yo ap fe fas",
        ),
        (
            r"\bmwen gen avem\.?\s+mwen yon bell ekip\b",
            "mwen gen avèk mwen yon bèl ekip",
        ),
        (
            r"\bmwen gen avem\.?\s+mwen yon bel ekip\b",
            "mwen gen avèk mwen yon bèl ekip",
        ),
        (
            r"\bki ap\.?\s+ou jwen\.?\s+nou ti kras pita\b",
            "ki ap rejwenn nou yon ti kras pita",
        ),
        (
            r"\bpodcast sa social medicine on hair\b",
            "podcast sa Social Medicine on Air",
        ),
        (
            r"\bsocial medicine on the air la[, ]+k ap fè yon\s+bèl travay\b",
            "Social Medicine on the air la, k ap fè yon bèl travay",
        ),
    )

    for pattern, replacement in repairs:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    return text


def _is_ht_spell_candidate(token: str, lexicon: frozenset[str]) -> bool:
    clean = token.strip(".,!?;:()[]{}\"'")
    if len(clean) < 4:
        return False

    lower = clean.lower()
    if lower in lexicon or lower in HT_DO_NOT_TOUCH:
        return False

    # Avoid touching names, acronyms, or mixed technical-ish tokens.
    if clean.isupper() or clean[:1].isupper():
        return False
    if any(ch.isdigit() for ch in clean):
        return False
    if "-" in clean or "'" in clean:
        return False

    return clean.isalpha()


def _apply_ht_conservative_spelling_rescue(text: str) -> str:
    lexicon = _load_ht_spelling_lexicon()

    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        if not _is_ht_spell_candidate(token, lexicon):
            return token

        low = token.lower()
        candidates = difflib.get_close_matches(low, lexicon, n=1, cutoff=0.93)
        if not candidates:
            return token

        candidate = candidates[0]
        if abs(len(candidate) - len(low)) > 1:
            return token
        if low[:1] != candidate[:1]:
            return token

        return _apply_case_style(token, candidate)

    return HT_WORD_RE.sub(repl, text)


def _remove_simple_repetition(text: str) -> str:
    return re.sub(r"\b(\w+)\s+\1\b", r"\1", text)


def split_into_natural_paragraphs(
    text: str,
    *,
    target_sentences: int = 3,
    max_sentences: int = 5,
) -> List[str]:
    if not text:
        return []

    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", text)
        if sentence.strip()
    ]
    if not sentences:
        return []

    paragraphs: List[str] = []
    current: List[str] = []

    for sentence in sentences:
        current.append(sentence)
        should_break = len(current) >= max_sentences
        if len(current) >= target_sentences and re.search(r"[.!?]$", sentence):
            should_break = True

        if should_break:
            paragraphs.append(" ".join(current).strip())
            current = []

    if current:
        paragraphs.append(" ".join(current).strip())

    return paragraphs


# ------------------------------------------------------------
# TEXT-ONLY FORMATTING (your original logic)
# ------------------------------------------------------------
def apply_formatting(text: str, *, language: str | None = None) -> str:
    """
    Final-stage linguistic formatting.
    Runs AFTER all correction layers.
    Safe, deterministic, and language-aware.
    """
    if not text:
        return text

    # 1. Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    if language == "ht":
        text = _apply_ht_token_fixes(text)
        text = _apply_ht_spacing_repairs(text)
        text = _apply_ht_akademi_fixes(text)
        text = _apply_ht_conservative_spelling_rescue(text)
        text = _apply_ht_phrase_repairs(text)
        text = _remove_simple_repetition(text)

    # 2. Insert some conservative sentence boundaries
    text = _insert_natural_sentence_breaks(text)

    # 3. Punctuation spacing cleanup
    text = _cleanup_punctuation_spacing(text)

    # 4. Sentence capitalization
    text = _capitalize_sentences(text)

    # 5. Haitian Creole–specific cleanup
    text = re.sub(r"\byo(?:\s+yo)+\b", "yo", text)

    # 6. Final punctuation and whitespace polish
    text = _cleanup_punctuation_spacing(text)
    text = re.sub(r"\s{2,}", " ", text)
    text = _normalize_terminal_punctuation(text)

    return text.strip()


# ------------------------------------------------------------
# SPEAKER STRUCTURE FORMATTING
# ------------------------------------------------------------
def format_speaker_transcript(
    segments: List[Dict],
    speaker_key: str = "speaker",
    text_key: str = "text",
    *,
    language: str | None = None,
) -> str:
    """
    Convert Whisper-like segments into clean speaker blocks.
    """

    if not segments:
        return ""

    blocks = []
    current_speaker = None
    buffer = []

    for seg in segments:
        speaker = seg.get(speaker_key, "Speaker 1")
        text = seg.get(text_key, "").strip()

        if not text:
            continue

        # Apply linguistic formatting per segment
        text = apply_formatting(text, language=language)

        if speaker != current_speaker:
            if buffer:
                blocks.append(
                    f"{current_speaker}:\n" + "\n\n".join(split_into_natural_paragraphs(" ".join(buffer)))
                )
                buffer = []

            current_speaker = speaker

        buffer.append(text)

    if buffer:
        blocks.append(
            f"{current_speaker}:\n" + "\n\n".join(split_into_natural_paragraphs(" ".join(buffer)))
        )

    return "\n\n".join(blocks)
