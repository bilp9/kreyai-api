from __future__ import annotations

from typing import Dict
from math import isfinite


def compute_speaker_a3_confidence(stats: Dict) -> float:
    restricted = stats.get("restricted", 0)
    full = stats.get("full", 0)
    reverted = stats.get("reverted", 0)
    avg_ht = stats.get("avg_ht_density", 0.0)

    denom = restricted + full + 1

    R = restricted / denom
    H = max(0.1, min(avg_ht, 1.0))
    P = reverted / denom

    confidence = (0.6 * R + 0.4 * H) * (1 - P)

    if not isfinite(confidence):
        return 0.0

    return round(max(0.0, min(confidence, 1.0)), 3)
