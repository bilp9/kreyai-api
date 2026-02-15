# app/transcription/akademi_validator.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict


# Conservative: Creole orthography-ish token pattern (allows diacritics + apostrophe)
CREOLE_TOKEN_RE = re.compile(r"^[a-zàâèéêîôùûçòò̈]+(?:'[a-zàâèéêîôùûçòò̈]+)?$", re.IGNORECASE)

# Words we never want Akademi validator to “approve” as Creole corrections
BLOCKLIST = {
    "aws", "ec2", "s3", "iam", "kms", "http", "https",
}


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason: str
    confidence: float = 0.0


class AkademiKreyolValidator:
    """
    Validator-only interface.

    Later, you can back this with:
      - Akademi Kreyòl official wordlists
      - orthography docs
      - approved morphology rules
    But it NEVER invents corrections; it only validates candidates.
    """

    def __init__(self, lexicon: Optional[Dict[str, bool]] = None):
        # lexicon maps normalized word -> True
        self.lexicon = lexicon or {}

    def validate_candidate(self, before: str, after: str) -> ValidationResult:
        b = (before or "").strip().lower()
        a = (after or "").strip().lower()

        if not b or not a:
            return ValidationResult(False, "empty")

        # Never validate technical tokens
        if b in BLOCKLIST or a in BLOCKLIST:
            return ValidationResult(False, "blocked_tech_token")

        # If replacement introduces non-creole-ish token shape, reject
        # (You can relax this later.)
        if not CREOLE_TOKEN_RE.match(a.replace(" ", "")) and " " not in a:
            return ValidationResult(False, "not_creole_token_shape")

        # If you have lexicon coverage, require 'after' to be known OR partially known
        if self.lexicon:
            if a in self.lexicon:
                return ValidationResult(True, "lexicon_hit", confidence=0.95)
            # allow spaced phrase if every token is known
            toks = [t for t in a.split() if t]
            if toks and all(t in self.lexicon for t in toks):
                return ValidationResult(True, "lexicon_phrase_hit", confidence=0.90)
            return ValidationResult(False, "lexicon_miss")

        # If no lexicon loaded yet, only do structural validation
        return ValidationResult(True, "structure_only", confidence=0.60)
