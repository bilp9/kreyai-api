from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Tuple

DICT_PATH = Path(__file__).parent / "data" / "dictionary.json"

_CACHE: Dict[str, Tuple[float, dict]] = {}
TTL_SECONDS = 5  # hot reload window


def load_dictionary() -> dict:
    now = time.time()

    cached = _CACHE.get("dictionary")
    if cached:
        ts, data = cached
        if now - ts < TTL_SECONDS:
            return data

    if not DICT_PATH.exists():
        data = {}
    else:
        with open(DICT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

    _CACHE["dictionary"] = (now, data)
    return data
