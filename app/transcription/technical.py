from __future__ import annotations

import re
from typing import Tuple, List


# ============================================================
# SEGMENT-LEVEL TECH LEXICON (regex over full text)
# ============================================================

TECH_LEXICON = {
    # phonetic_pattern : canonical_form
    r"\bissitou\b": "EC2",
    r"\bss3[-\s]?s3\b": "S3",
    r"\bssi[-\s]?kms\b": "AWS KMS",
}

# multi-token expansions (confidence-gated)
MULTI_TOKEN = [
    {
        "pattern": r"\binstantemoyo\b",
        "replacement": "instances mwen yo",
        "confidence": 0.85,
    }
]


# ============================================================
# SEGMENT-LEVEL TECH CORRECTION
# ============================================================

def apply_technical_bias(
    text: str,
    confidence: float = 1.0,
    enabled: bool = True,
) -> Tuple[str, List[str]]:
    """
    Applies safe, opt-in technical corrections at the TEXT level.

    Intended usage:
    - segment-level correction
    - confidence-gated expansions
    - coarse ASR phonetic repair
    """

    if not enabled or not text:
        return text, []

    out = text
    log: List[str] = []

    # --- single-token regex replacements
    for pattern, replacement in TECH_LEXICON.items():
        if re.search(pattern, out):
            out = re.sub(pattern, replacement, out)
            log.append(f"tech: {pattern} → {replacement}")

    # --- multi-token expansions (confidence gated)
    for rule in MULTI_TOKEN:
        if confidence >= rule["confidence"]:
            if re.search(rule["pattern"], out):
                out = re.sub(rule["pattern"], rule["replacement"], out)
                log.append(
                    f"tech: {rule['pattern']} → {rule['replacement']} "
                    f"(conf ≥ {rule['confidence']})"
                )

    return out, log


# ============================================================
# TOKEN-LEVEL HELPERS (PRIVATE)
# ============================================================

_PUNCT_RE = re.compile(r"^([\"'(\[{<]*)(.*?)([\"')\]}>.,;:!?]*)$")


def _split_punct(token: str) -> tuple[str, str, str]:
    """
    Returns (prefix_punct, core, suffix_punct)
    Preserves punctuation around a token.
    """
    m = _PUNCT_RE.match(token.strip())
    if not m:
        return "", token.strip(), ""
    return m.group(1), m.group(2), m.group(3)


def _norm(core: str) -> str:
    """
    Normalize token for matching:
    - lowercase
    - normalize apostrophes
    - strip hyphens/underscores
    - collapse whitespace
    """
    c = core.lower()
    c = c.replace("’", "'")
    c = re.sub(r"[-_]", "", c)
    c = re.sub(r"\s+", " ", c).strip()
    return c


# ============================================================
# TOKEN-LEVEL TECH RESOLVER
# ============================================================

def resolve_tech_phrases(token: str) -> Tuple[str, List[str]]:
    """
    Token-aware technical resolver.

    Input:
        single token (string)

    Output:
        corrected token string (may expand to multiple words),
        plus audit log
    """

    if not token or not token.strip():
        return token, []

    pre, core, post = _split_punct(token)
    if not core:
        return token, []

    raw_core = core
    c = _norm(core)
    log: List[str] = []

    # --------------------------------------------------------
    # Canonical AWS / tech acronyms (uppercase)
    # --------------------------------------------------------

    acronym_map = {
        "ec2": "EC2",
        "s3": "S3",
        "kms": "KMS",
        "iam": "IAM",
        "vpc": "VPC",
        "rds": "RDS",
        "sns": "SNS",
        "sqs": "SQS",
        "ecr": "ECR",
        "ecs": "ECS",
        "eks": "EKS",
        "cloudwatch": "CloudWatch",
        "route53": "Route 53",
        "dynamodb": "DynamoDB",
        "cloudformation": "CloudFormation",
        "cloudfront": "CloudFront",
        "lambda": "Lambda",
    }

    # --------------------------------------------------------
    # Phonetic EC2 variants (ASR damage)
    # --------------------------------------------------------

    phonetic_map = {
        "issitou": "EC2",
        "isitou": "EC2",
        "ecde": "EC2",
        "esitou": "EC2",
    }

    # --------------------------------------------------------
    # Multi-token phrase repairs (token-level)
    # --------------------------------------------------------

    # "instantemoyo" ≈ "instances mwen yo"
    if (
        re.fullmatch(r"instan(?:c|s)?e?moyo", c)
        or re.fullmatch(r"instan(?:c|s)?e?mwenyo", c)
        or (c.startswith("instan") and ("moyo" in c or "mwenyo" in c))
    ):
        fixed = "instances mwen yo"
        log.append(f"tech: {raw_core} → {fixed}")
        return f"{pre}{fixed}{post}", log

    # --------------------------------------------------------
    # French leakage cleanup (token-aware)
    # --------------------------------------------------------

    # "instant" (FR) → "enstan" (HT)
    if c == "instant":
        fixed = "enstan"
        log.append(f"lang: {raw_core} → {fixed} (FR→HT)")
        return f"{pre}{fixed}{post}", log

    # --------------------------------------------------------
    # Direct acronym match
    # --------------------------------------------------------

    if c in acronym_map:
        fixed = acronym_map[c]
        if fixed != raw_core:
            log.append(f"tech: {raw_core} → {fixed}")
        return f"{pre}{fixed}{post}", log

    # Acronym with punctuation / hyphens (e.g., "k-m-s", "s3,")
    compact = re.sub(r"[^a-z0-9]", "", c)
    if compact in acronym_map:
        fixed = acronym_map[compact]
        log.append(f"tech: {raw_core} → {fixed}")
        return f"{pre}{fixed}{post}", log

    # Phonetic acronym fallback
    if c in phonetic_map:
        fixed = phonetic_map[c]
        log.append(f"tech: {raw_core} → {fixed} (phonetic)")
        return f"{pre}{fixed}{post}", log

    # --------------------------------------------------------
    # No change
    # --------------------------------------------------------

    return token, []
