import re
from typing import Tuple, List

LEXICAL_CORRECTIONS = {
    "apriti": "ap vini",
    "voa": "vwa",
    "bagia": "bagay",
    "technologia": "teknoloji",
    "prisentasyom": "prezantasyon",
    "mutet": "mute",
}

def apply_lexical_corrections(text: str) -> Tuple[str, List[str]]:
    if not text:
        return text, []

    logs = []

    for wrong, correct in LEXICAL_CORRECTIONS.items():
        pattern = rf"\b{re.escape(wrong)}\b"
        if re.search(pattern, text):
            text = re.sub(pattern, correct, text)
            logs.append(f"{wrong} → {correct}")

    return text, logs
