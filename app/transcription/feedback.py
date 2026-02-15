# app/transcription/feedback.py
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

# -------------------------------------------------------------------
# Storage
# -------------------------------------------------------------------

FEEDBACK_PATH = Path("app/storage/feedback.jsonl")
FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)

# -------------------------------------------------------------------
# Low-level writer (generic, reusable)
# -------------------------------------------------------------------

def _write_event(event: Dict) -> None:
    event["timestamp"] = datetime.utcnow().isoformat()

    with FEEDBACK_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

# -------------------------------------------------------------------
# Public API (structured feedback)
# -------------------------------------------------------------------

def record_feedback(
    *,
    original: str,
    corrected: str,
    category: str,
    confidence: Optional[float] = None,
) -> None:
    """
    Record a structured feedback event for transcription corrections.
    """
    event = {
        "original": original,
        "corrected": corrected,
        "category": category,
        "confidence": confidence,
    }

    _write_event(event)
