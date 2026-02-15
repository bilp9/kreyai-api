# app/transcription/validators/akademi.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict
from pathlib import Path
import json

# -------------------------------------------------
# Policy
# -------------------------------------------------
# Akademi is a validator, not a source of truth.
# It NEVER modifies text.
# It only returns confidence signals.
# -------------------------------------------------


@dataclass(frozen=True)
class AkademiValidationResult:
    valid: bool
    confidence: float           # 0.0 – 1.0
    source: str = "akademi"
    notes: Optional[str] = None


class AkademiValidator:
    """
    Lightweight validator for Haitian Creole lexical legitimacy.

    This validator:
    - never injects words
    - never overrides transcription
    - only validates tokens already produced by the system
    """

    def __init__(self, lexicon_path: Optional[Path] = None):
        self.lexicon: Dict[str, float] = {}

        if lexicon_path and lexicon_path.exists():
            self._load_lexicon(lexicon_path)

    def _load_lexicon(self, path: Path):
        """
        Load a *curated*, legally obtained Akademi word list.

        Expected format:
        {
            "mwen": 1.0,
            "ap": 1.0,
            "bezwen": 0.9
        }
        """
        with open(path, "r", encoding="utf-8") as f:
            self.lexicon = json.load(f)

    # -------------------------------------------------
    # Public API
    # -------------------------------------------------
    def validate_token(self, token: str) -> AkademiValidationResult:
        """
        Validate a single token.

        This function is intentionally:
        - side-effect free
        - conservative
        """
        key = token.lower()

        if key in self.lexicon:
            return AkademiValidationResult(
                valid=True,
                confidence=self.lexicon.get(key, 0.8),
            )

        return AkademiValidationResult(
            valid=False,
            confidence=0.0,
            notes="not found in akademi lexicon",
        )
def validate_tokens(self, tokens: Iterable[str]) -> Dict[str, AkademiValidationResult]:
    return {t: self.validate_token(t) for t in tokens}
