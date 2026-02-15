# scripts/ingest_akademi_pdf.py
from __future__ import annotations

import re
import json
from pathlib import Path
from collections import Counter

import pdfplumber

RAW_DIR = Path("data/akademi/raw")
OUT_PATH = Path("data/akademi/processed/lexicon.json")

TOKEN_RE = re.compile(r"[a-zA-Zàâèéêîôùûç]+", re.IGNORECASE)


def normalize(token: str) -> str:
    return token.lower().strip()


def extract_tokens_from_pdf(path: Path) -> list[str]:
    tokens: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            tokens.extend(TOKEN_RE.findall(text))
    return [normalize(t) for t in tokens if len(t) >= 2]


def main():
    counter = Counter()

    for pdf in RAW_DIR.glob("*.pdf"):
        print(f"Processing {pdf.name}")
        tokens = extract_tokens_from_pdf(pdf)
        counter.update(tokens)

    # Frequency → confidence (simple, conservative heuristic)
    lexicon = {
        token: min(1.0, 0.5 + count / 20.0)
        for token, count in counter.items()
        if count >= 2
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(lexicon, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"✓ Lexicon written to {OUT_PATH}")
    print(f"✓ Tokens: {len(lexicon)}")


if __name__ == "__main__":
    main()
