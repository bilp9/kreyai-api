import re
from typing import Tuple, List

LEXICAL_CORRECTIONS = {
    "apriti": "ap vini",
    "voa": "vwa",
    "bagia": "bagay",
    "technologia": "teknoloji",
    "prisentasyom": "prezantasyon",
    "mutet": "mute",
    "pouje": "pwojè",
    "poujet": "pwojè",
    "edukasyon": "edikasyon",
    "foa": "fwa",
    "rendi": "rendy",
}


def _apply_case_style(source: str, replacement: str) -> str:
    if not source:
        return replacement
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper() and source[1:].islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def apply_lexical_corrections(text: str) -> Tuple[str, List[str]]:
    if not text:
        return text, []

    logs = []

    for wrong, correct in LEXICAL_CORRECTIONS.items():
        pattern = rf"\b{re.escape(wrong)}\b"
        if re.search(pattern, text, flags=re.IGNORECASE):
            def repl(match: re.Match[str]) -> str:
                return _apply_case_style(match.group(0), correct)

            text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
            logs.append(f"{wrong} → {correct}")

    return text, logs
