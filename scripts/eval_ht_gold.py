# scripts/eval_ht_gold.py
from __future__ import annotations

import json
import re
from pathlib import Path
from collections import Counter

# -------------------------------------------------
# Paths
# -------------------------------------------------
HT_GOLD_DIR = Path("data/ht_gold")
AKADEMI_LEXICON = Path("data/akademi/processed/lexicon.json")
DOMAIN_LEXICON_DIR = Path("data/lexicon/domain")

# -------------------------------------------------
# Token filters
# -------------------------------------------------
CLITICS = {"m", "l", "t", "w", "a", "k", "p"}
ANNOTATION_RE = re.compile(r"\[.*?\]")
TOKEN_RE = re.compile(r"[a-zàâèéêëîïôùûüç\-]+")


def normalize(text: str) -> str:
    text = text.lower()
    text = ANNOTATION_RE.sub("", text)
    return text


def tokenize(text: str):
    return TOKEN_RE.findall(text)


# -------------------------------------------------
# Load lexicons
# -------------------------------------------------
with open(AKADEMI_LEXICON, "r", encoding="utf-8") as f:
    akademi = json.load(f)

domain_tokens = {}
if DOMAIN_LEXICON_DIR.exists():
    for p in DOMAIN_LEXICON_DIR.glob("*.json"):
        with open(p, "r", encoding="utf-8") as f:
            domain_tokens.update(json.load(f))


# -------------------------------------------------
# Load HT gold text
# -------------------------------------------------
texts = []
for p in HT_GOLD_DIR.glob("*.txt"):
    texts.append(p.read_text(encoding="utf-8"))

full_text = normalize("\n".join(texts))
tokens = tokenize(full_text)

# -------------------------------------------------
# Filter noise
# -------------------------------------------------
filtered = [
    t for t in tokens
    if t not in CLITICS
]

total = len(filtered)

ak_hits = 0
domain_hits = 0
unknown = Counter()

for tok in filtered:
    if tok in akademi:
        ak_hits += 1
    elif tok in domain_tokens:
        domain_hits += 1
    else:
        unknown[tok] += 1

coverage = (ak_hits + domain_hits) / max(1, total)

# -------------------------------------------------
# Report
# -------------------------------------------------
print("\nHT GOLD EVALUATION (CLEANED)")
print("-" * 30)
print(f"Total tokens        : {total}")
print(f"Akademi covered     : {ak_hits}")
print(f"Domain covered      : {domain_hits}")
print(f"Overall coverage    : {coverage:.2%}")

print("\nTop unknown tokens:")
for tok, cnt in unknown.most_common(15):
    print(f"  {tok}: {cnt}")
