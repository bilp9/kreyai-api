from __future__ import annotations

import os
import re
from typing import Dict, Tuple


PLACEHOLDER_PREFIX = "__CSHIELD_"


CODE_SWITCH_PHRASES = [
    re.compile(r"\bparce que\b", flags=re.IGNORECASE),
    re.compile(r"\btr[eè]s bien\b", flags=re.IGNORECASE),
    re.compile(r"\bavec deux\b", flags=re.IGNORECASE),
    re.compile(r"\bnon[- ]profit\b", flags=re.IGNORECASE),
]


CODE_SWITCH_TOKENS = {
    "avec",
    "deux",
    "officially",
    "organization",
    "organizations",
    "created",
    "invited",
    "same",
    "year",
    "officially",
    "non-profit",
    "profit",
    "because",
    "project",
    "problems",
    "problem",
    "education",
    "vision",
    "we",
    "the",
    "and",
    "malheureusement",
    "vulnerable",
}


TOKEN_RE = re.compile(r"\b[\w-]+\b", flags=re.UNICODE)
MANGLED_PLACEHOLDER_RE = re.compile(
    r"_*\s*CSHIELD\s*_*\s*(\d{1,6})\s*_+",
    flags=re.IGNORECASE,
)
UNRESTORED_PLACEHOLDER_RE = re.compile(r"__CSHIELD_(\d{4,6})__", flags=re.IGNORECASE)


def _code_switch_shield_enabled() -> bool:
    raw = os.getenv("KREYAI_HT_ENABLE_CODE_SWITCH_SHIELD")
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _protect_pattern_spans(
    text: str,
    pattern: re.Pattern[str],
    replacements: Dict[str, str],
) -> str:
    def repl(match: re.Match[str]) -> str:
        placeholder = f"{PLACEHOLDER_PREFIX}{len(replacements):04d}__"
        replacements[placeholder] = match.group(0)
        return placeholder

    return pattern.sub(repl, text)


def shield_code_switch_spans(text: str) -> Tuple[str, Dict[str, str]]:
    """
    Protect obvious French/English spans from Creole normalization.
    The detector is intentionally conservative and only shields spans we are
    reasonably confident are non-Creole code-switches.
    """

    if not text or not _code_switch_shield_enabled():
        return text, {}

    out = text
    replacements: Dict[str, str] = {}

    for pattern in CODE_SWITCH_PHRASES:
        out = _protect_pattern_spans(out, pattern, replacements)

    protected_parts = []
    last_end = 0
    for match in TOKEN_RE.finditer(out):
        protected_parts.append(out[last_end:match.start()])
        token = match.group(0)
        if token.lower() in CODE_SWITCH_TOKENS:
            placeholder = f"{PLACEHOLDER_PREFIX}{len(replacements):04d}__"
            replacements[placeholder] = token
            protected_parts.append(placeholder)
        else:
            protected_parts.append(token)
        last_end = match.end()

    protected_parts.append(out[last_end:])
    return "".join(protected_parts), replacements


def restore_code_switch_spans(text: str, replacements: Dict[str, str]) -> str:
    if not text or not replacements:
        return text

    restored = text
    for placeholder, original in replacements.items():
        restored = restored.replace(placeholder, original)

    def repl(match: re.Match[str]) -> str:
        key = f"{PLACEHOLDER_PREFIX}{int(match.group(1)):04d}__"
        return replacements.get(key, match.group(0))

    restored = MANGLED_PLACEHOLDER_RE.sub(repl, restored)
    return restored


def has_unrestored_code_switch_placeholders(text: str) -> bool:
    return bool(text and UNRESTORED_PLACEHOLDER_RE.search(text))
