from typing import List, Dict

def extract_tokens(segments) -> List[Dict]:
    tokens = []

    for seg in segments:
        seg_logprob = seg.avg_logprob

        if not hasattr(seg, "words") or not seg.words:
            continue

        for w in seg.words:
            tokens.append({
                "text": w.word.strip(),
                "start": w.start,
                "end": w.end,
                "segment_logprob": seg_logprob,
            })

    return tokens
