from typing import List, Dict, Tuple


def get_confidence_tier(seg: Dict) -> str:
    """
    Classify a segment into coarse confidence tiers.

    Tiers:
    - high: strong decode confidence
    - medium: usable, but still somewhat uncertain
    - low: weak decode confidence
    - review: likely silence / hallucination / should be handled carefully
    """

    avg_logprob = seg.get("avg_logprob")
    no_speech_prob = seg.get("no_speech_prob")
    hallucinated = bool(seg.get("hallucinated", False))

    if hallucinated:
        return "review"

    if no_speech_prob is not None and no_speech_prob > 0.6:
        return "review"

    if avg_logprob is None:
        return "medium"

    if avg_logprob >= -0.5:
        return "high"

    if avg_logprob >= -1.0:
        return "medium"

    if avg_logprob >= -1.5:
        return "low"

    return "review"


def is_low_confidence(seg: Dict) -> bool:
    """
    Determine whether a segment is low confidence.

    Rules:
    - avg_logprob below threshold
    - or high no_speech_prob
    """

    return get_confidence_tier(seg) in {"low", "review"}


def split_segments_by_confidence(
    segments: List[Dict],
) -> Tuple[List[Dict], List[Dict]]:
    """
    Split segments into high- and low-confidence buckets.

    Returns:
      high_confidence_segments,
      low_confidence_segments
    """

    high_conf: List[Dict] = []
    low_conf: List[Dict] = []

    for seg in segments:
        if is_low_confidence(seg):
            low_conf.append(seg)
        else:
            high_conf.append(seg)

    return high_conf, low_conf
