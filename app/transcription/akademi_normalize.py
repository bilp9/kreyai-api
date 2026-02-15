from __future__ import annotations

from typing import Dict
import difflib
import re

_WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)


class AkademiNormalizer:
    def __init__(self, lexicon: Dict[str, float]):
        self.lexicon = lexicon
        self.words = set(lexicon.keys())

    def normalize_text(self, text: str) -> str:
        """
        Stabilize HT tokens using Akademi lexicon.
        Conservative by design.
        """
        if not text:
            return text

        def replace(match):
            token = match.group(0)
            low = token.lower()

            # Exact Akademi hit → protect
            if low in self.words:
                return token

            # Close match → snap (very conservative)
            candidates = difflib.get_close_matches(
                low, self.words, n=1, cutoff=0.92
            )
            if candidates:
                return candidates[0]

            return token

        return _WORD_RE.sub(replace, text)
