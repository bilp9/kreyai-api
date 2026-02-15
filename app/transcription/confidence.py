from typing import List, Dict, Tuple


def is_low_confidence(seg: Dict) -> bool:
    """
    Determine whether a segment is low confidence.

    Rules:
    - avg_logprob below threshold
    - or high no_speech_prob
    """

    avg_logprob = seg.get("avg_logprob")
    no_speech_prob = seg.get("no_speech_prob", 0.0)

    if avg_logprob is not None and avg_logprob < -1.0:
        return True

    if no_speech_prob is not None and no_speech_prob > 0.6:
        return True

    return False


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
