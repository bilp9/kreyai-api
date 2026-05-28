from __future__ import annotations

import re
from typing import Any, Dict

from app.transcription.formatting import apply_formatting
from app.transcription.code_switch import restore_code_switch_spans, shield_code_switch_spans
from app.services.ht_llm_review import run_ht_llm_review


HT_RECURRING_TOKEN_FIXES = {
    "toutmon": "tout moun",
    "toutmoun": "tout moun",
    "mem": "menm",
    "ansem": "ansanm",
    "anse m": "ansanm",
    "bref": "brèf",
    "rejoen": "rejwenn",
    "rejo en": "rejwenn",
    "jo di": "jodi",
    "jodi ya": "jodi a",
    "jodi la": "jodi a",
    "anan": "an",
    "seyon": "se yon",
}

HT_RECURRING_PHRASE_FIXES = (
    (
        r"\bnon pa m(?:\s+se|\.)?\s+",
        "non pa m se ",
    ),
    (
        r"\bmwen kontan avèk\.?\s+nou\b",
        "mwen kontan avèk nou",
    ),
    (
        r"\bmwen gen avèk mwen yon b[eè]l ekip\b",
        "mwen gen avèk mwen yon bèl ekip",
    ),
    (
        r"\bmwen gen avem\.?\s+mwen\b",
        "mwen gen avèk mwen",
    ),
    (
        r"\bki ap(?:ou)?\s+jwenn nou ti kras pita\b",
        "ki ap rejwenn nou yon ti kras pita",
    ),
    (
        r"\bsocial medicine on(?:\s+the)?\s+hair\b",
        "Social Medicine on Air",
    ),
    (
        r"\bmouvement medicine sosyal\b",
        "mouvman medsin sosyal",
    ),
    (
        r"\bmouvement medtine sosyal\b",
        "mouvman medsin sosyal",
    ),
    (
        r"\bpwofesyon[eè]l sante yo avèk pasyon yo ap fe fas\b",
        "pwofesyonèl sante yo avèk pasyan yo ap fè fas",
    ),
)


def _apply_recurring_token_fixes(text: str) -> str:
    updated = text
    for wrong, correct in HT_RECURRING_TOKEN_FIXES.items():
        updated = re.sub(rf"\b{re.escape(wrong)}\b", correct, updated, flags=re.IGNORECASE)
    return updated


def _apply_recurring_phrase_fixes(text: str) -> str:
    updated = text
    for pattern, replacement in HT_RECURRING_PHRASE_FIXES:
        updated = re.sub(pattern, replacement, updated, flags=re.IGNORECASE)
    return updated


def _normalize_minor_punctuation(text: str) -> str:
    updated = re.sub(r"\s*,\s*,+", ", ", text)
    updated = re.sub(r"\s+\.\s*", ". ", updated)
    updated = re.sub(r"\s{2,}", " ", updated)
    updated = re.sub(r"\n{3,}", "\n\n", updated)
    return updated.strip()


def apply_rule_cleanup(raw_text: str, *, metadata: Dict[str, Any] | None = None) -> str:
    _ = metadata
    shielded_text, code_switch_replacements = shield_code_switch_spans(raw_text)
    cleaned = apply_formatting(shielded_text, language="ht").strip()
    cleaned = _apply_recurring_token_fixes(cleaned)
    cleaned = _apply_recurring_phrase_fixes(cleaned)
    cleaned = _normalize_minor_punctuation(cleaned)
    cleaned = restore_code_switch_spans(cleaned, code_switch_replacements)
    return cleaned


def run_ht_cleanup_pipeline(raw_text: str, metadata: Dict[str, Any] | None = None) -> str:
    return apply_rule_cleanup(raw_text, metadata=metadata)


def run_ht_cleanup_pipeline_with_llm(raw_text: str, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
    cleaned = apply_rule_cleanup(raw_text, metadata=metadata)
    return run_ht_llm_review(cleaned)
