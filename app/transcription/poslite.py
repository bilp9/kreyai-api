from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple, Optional

# ----------------------------
# POS-lite vocabulary
# ----------------------------

TMA = {
    "ap", "pral", "te", "ta", "tap", "t ap",
    "va", "a",
}

NEG = {"pa", "p"}

PRON = {
    "m", "mwen",
    "w", "ou",
    "l", "li",
    "n", "nou",
    "yo",
}

BREAKERS = {
    "nan", "sou", "ak", "avèk", "pou", "de", "d", "a", "an", "ansanm",
    "ke", "k", "paske", "lè", "le", "si", "men", "epi", "e",
    "oswa", "oubyen",
}

TECH_TOKENS = {
    "ec2", "s3", "kms", "iam", "aws", "ssm",
    "kinesis", "lambda", "bedrock"
}

# ----------------------------
# Tokenization
# ----------------------------

TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+|[^\sA-Za-zÀ-ÖØ-öø-ÿ0-9]")

def tokenize(text: str) -> List[str]:
    return TOKEN_RE.findall(text)

def detokenize(tokens: List[str]) -> str:
    out: List[str] = []
    for t in tokens:
        if not out:
            out.append(t)
            continue
        if re.match(r"^[\.\,\!\?\:\;\)\]\}]$", t):
            out[-1] += t
        elif re.match(r"^[\(\[\{]$", t):
            out.append(t)
        else:
            if out[-1] in {"(", "[", "{"}:
                out.append(t)
            else:
                out.append(" " + t)
    return "".join(out)

def norm_token(t: str) -> str:
    return t.lower()

# ----------------------------
# POS-lite labels
# ----------------------------

@dataclass
class TaggedToken:
    raw: str
    norm: str
    tag: str  # PRON, TMA, NEG, WORD, PUNCT, TECH, BREAK

def tag_tokens(tokens: List[str]) -> List[TaggedToken]:
    tagged: List[TaggedToken] = []
    for tok in tokens:
        n = norm_token(tok)

        if re.fullmatch(r"[^\wÀ-ÖØ-öø-ÿ]+", tok):
            tagged.append(TaggedToken(tok, n, "PUNCT"))
        elif n in TECH_TOKENS or re.fullmatch(r"[a-z]+[0-9]+", n):
            tagged.append(TaggedToken(tok, n, "TECH"))
        elif n in PRON:
            tagged.append(TaggedToken(tok, n, "PRON"))
        elif n in NEG:
            tagged.append(TaggedToken(tok, n, "NEG"))
        elif n in BREAKERS:
            tagged.append(TaggedToken(tok, n, "BREAK"))
        elif n in TMA:
            tagged.append(TaggedToken(tok, n, "TMA"))
        else:
            tagged.append(TaggedToken(tok, n, "WORD"))

    return tagged

# ----------------------------
# Helpers
# ----------------------------

def _is_wordlike(tt: TaggedToken) -> bool:
    return tt.tag == "WORD"

def _is_break(tt: TaggedToken) -> bool:
    return tt.tag in {"BREAK", "PUNCT"}

# ----------------------------
# C3 — Verb phrase normalization
# ----------------------------

def normalize_verb_phrases(text: str) -> Tuple[str, List[str]]:
    tokens = tokenize(text)
    tagged = tag_tokens(tokens)
    log: List[str] = []

    new_tokens: List[str] = []

    for tt in tagged:
        if tt.tag == "WORD":
            n = tt.norm

            if n.startswith("ap") and len(n) > 3 and n != "ap":
                remainder = tt.raw[2:]
                if remainder[0].isalpha():
                    new_tokens.extend([tt.raw[:2], remainder])
                    log.append(f"split: {tt.raw} → {tt.raw[:2]} {remainder}")
                    continue

            if n.startswith("pral") and len(n) > 4:
                remainder = tt.raw[4:]
                if remainder[0].isalpha():
                    new_tokens.extend([tt.raw[:4], remainder])
                    log.append(f"split: {tt.raw} → {tt.raw[:4]} {remainder}")
                    continue

        new_tokens.append(tt.raw)

    return detokenize(new_tokens), log

# ----------------------------
# C3.1 — Pronoun + TMA normalization
# ----------------------------

APOSTROPHE_RE = re.compile(
    r"(m|n|l|w|y|nou|yo)\s*[’']\s*(ap|te|ta|tap)",
    re.IGNORECASE
)

FUSED_TMA = {
    "tap": "te ap",
    "nap": "n ap",
    "map": "m ap",
    "lap": "l ap",
    "wap": "w ap",
}

def normalize_pronoun_tma(text: str) -> Tuple[str, List[str]]:
    log: List[str] = []
    out = text

    def _apostrophe_fix(match):
        before = match.group(0)
        after = f"{match.group(1)} {match.group(2)}"
        log.append(f"{before} → {after}")
        return after

    out = APOSTROPHE_RE.sub(_apostrophe_fix, out)

    tokens = tokenize(out)
    new_tokens: List[str] = []

    for tok in tokens:
        n = tok.lower()
        if n in FUSED_TMA:
            expanded = FUSED_TMA[n]
            new_tokens.extend(expanded.split())
            log.append(f"{tok} → {expanded}")
        else:
            new_tokens.append(tok)

    return detokenize(new_tokens), log
