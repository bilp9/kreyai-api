from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List

import httpx


DEFAULT_MODEL = os.getenv("OPENAI_HT_REVIEW_MODEL", "gpt-4o-mini")
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
MAX_GLOSSARY_TERMS = 80
MAX_GLOSSARY_TERM_CHARS = 120
DEFAULT_PROMPT = """You are a Haitian Creole transcript orthography reviewer.

Only fix obvious Haitian Creole spelling, accents, spacing, and punctuation.

- Preserve meaning exactly
- Do NOT translate any word or phrase
- Do NOT paraphrase, summarize, rewrite, smooth, or improve style
- Do NOT replace English or French code-switching with Haitian Creole
- Do NOT replace Haitian Creole with French or English
- Keep names, organizations, places, speaker labels, and timestamps unchanged
- Keep natural spoken tone, repetitions, and false starts
- Fix only obvious Haitian Creole words, e.g. komanse -> kòmanse, kek -> kèk, tre -> trè, fet -> fèt, te -> tè only when the intended word is obvious from context
- If a phrase is unclear or the correction would require guessing, leave it unchanged

Return the same transcript with only obvious orthography fixes."""


def _env_glossary_terms() -> List[str]:
    raw = os.getenv("OPENAI_HT_REVIEW_GLOSSARY", "").strip()
    if not raw:
        return []
    return _normalize_glossary_terms(raw.replace("\n", ",").split(","))


@dataclass
class HTReviewChunk:
    index: int
    raw_text: str
    corrected_text: str
    notes: str
    needs_human_review: bool
    parse_error: bool = False


def _chunk_text(text: str, *, max_chars: int = 2200) -> List[str]:
    cleaned = str(text or "").strip()
    if not cleaned:
        return []

    paragraphs = [part.strip() for part in cleaned.split("\n\n") if part.strip()]
    if not paragraphs:
        paragraphs = [cleaned]

    chunks: List[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = paragraph
            continue

        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""

            start = 0
            while start < len(paragraph):
                end = min(start + max_chars, len(paragraph))
                chunks.append(paragraph[start:end].strip())
                start = end
            continue

        current = candidate

    if current:
        chunks.append(current)

    return chunks


def _normalize_glossary_terms(terms: Any) -> List[str]:
    if terms is None:
        return []

    raw_terms: List[str] = []
    if isinstance(terms, str):
        raw_terms = [terms]
    elif isinstance(terms, list):
        raw_terms = [str(term) for term in terms]
    else:
        return []

    normalized_terms: List[str] = []
    seen = set()
    for term in raw_terms:
        cleaned = " ".join(str(term or "").split()).strip()
        if not cleaned:
            continue
        cleaned = cleaned[:MAX_GLOSSARY_TERM_CHARS].strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized_terms.append(cleaned)

    return normalized_terms[:MAX_GLOSSARY_TERMS]


def _response_output_text(payload: Dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return str(payload["output_text"])

    output = payload.get("output")
    if isinstance(output, list):
        texts: List[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str):
                    texts.append(text)
        if texts:
            return "\n".join(texts)

    raise RuntimeError("OpenAI response did not include output text.")


def _extract_chunk_payload(payload_text: str, fallback_raw: str, index: int) -> HTReviewChunk:
    corrected_text = fallback_raw.strip()
    notes = ""
    needs_review = False

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        cleaned = payload_text.strip()
        if cleaned:
            corrected_text = cleaned
        return HTReviewChunk(
            index=index,
            raw_text=fallback_raw,
            corrected_text=corrected_text,
            notes="Model returned non-JSON output; treated as review text.",
            needs_human_review=True,
            parse_error=True,
        )

    if isinstance(payload, dict):
        candidate = payload.get("corrected_text")
        if isinstance(candidate, str) and candidate.strip():
            corrected_text = candidate.strip()
        notes_value = payload.get("change_notes")
        if isinstance(notes_value, str):
            notes = notes_value.strip()
        needs_review = bool(payload.get("needs_human_review"))

    return HTReviewChunk(
        index=index,
        raw_text=fallback_raw,
        corrected_text=corrected_text,
        notes=notes,
        needs_human_review=needs_review,
    )


def _format_glossary_terms(glossary_terms: List[str]) -> str:
    if not glossary_terms:
        return ""
    lines = "\n".join(f"- {term}" for term in glossary_terms)
    return (
        "\n\nKnown terms and names to preserve exactly when they appear or are clearly intended:\n"
        f"{lines}"
    )


def _postprocess_review_text(text: str, glossary_terms: List[str]) -> str:
    reviewed = str(text or "")
    if not reviewed:
        return reviewed

    glossary_keys = {term.casefold() for term in glossary_terms}
    if "projet saint-anne" in glossary_keys or "project saint-anne" in glossary_keys:
        reviewed = re.sub(
            r"\bpou\s+j[èe]\s+Saint[- ]Anne\b",
            "Projet Saint-Anne",
            reviewed,
            flags=re.IGNORECASE,
        )

    # A tiny deterministic accent repair for the common phrase we observed.
    reviewed = re.sub(r"\ban\s+kek\s+mo\b", "an kèk mo", reviewed, flags=re.IGNORECASE)
    return reviewed


def _build_input(
    prompt: str,
    chunk: str,
    index: int,
    total: int,
    *,
    glossary_terms: List[str] | None = None,
) -> List[Dict[str, str]]:
    schema_hint = {
        "corrected_text": "string",
        "change_notes": "short string",
        "needs_human_review": "boolean",
    }
    return [
        {
            "role": "system",
            "content": (
                f"{prompt}\n\n"
                "Use the glossary as a spelling/name anchor, but do not invent glossary terms where the audio text does not support them.\n"
                "Preserve transcript structure exactly: keep speaker labels and timestamps such as SPEAKER_00 (00:00:00) on their own lines, unchanged.\n"
                "Do not merge speakers, remove timestamps, rename speaker labels, or reorder transcript blocks.\n"
                f"{_format_glossary_terms(glossary_terms or [])}\n\n"
                "Return strict JSON only with this shape:\n"
                f"{json.dumps(schema_hint, ensure_ascii=False)}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Chunk {index + 1} of {total}.\n"
                "Preserve meaning exactly. Keep Haitian Creole. Keep code-switched English/French and known names unchanged.\n\n"
                f"{chunk}"
            ),
        },
    ]


def run_ht_llm_review(
    text: str,
    *,
    model: str | None = None,
    prompt: str | None = None,
    glossary_terms: List[str] | None = None,
    timeout_seconds: float = 120.0,
) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    selected_glossary_terms = _normalize_glossary_terms(
        [*_env_glossary_terms(), *(glossary_terms or [])]
    )

    raw_text = str(text or "").strip()
    if not raw_text:
        return {
            "model": model or DEFAULT_MODEL,
            "prompt": prompt or DEFAULT_PROMPT,
            "glossary_terms": selected_glossary_terms,
            "raw_text": "",
            "corrected_text": "",
            "chunks": [],
        }

    chunks = _chunk_text(raw_text)
    selected_model = (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    selected_prompt = (prompt or DEFAULT_PROMPT).strip() or DEFAULT_PROMPT
    reviewed_chunks: List[HTReviewChunk] = []

    with httpx.Client(timeout=timeout_seconds) as client:
        for index, chunk in enumerate(chunks):
            response = client.post(
                OPENAI_RESPONSES_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": selected_model,
                    "input": _build_input(
                        selected_prompt,
                        chunk,
                        index,
                        len(chunks),
                        glossary_terms=selected_glossary_terms,
                    ),
                },
            )
            response.raise_for_status()
            output_text = _response_output_text(response.json())
            reviewed_chunks.append(_extract_chunk_payload(output_text, chunk, index))

    corrected_text = "\n\n".join(
        chunk.corrected_text.strip()
        for chunk in reviewed_chunks
        if chunk.corrected_text.strip()
    ).strip()
    corrected_text = _postprocess_review_text(corrected_text, selected_glossary_terms).strip()

    return {
        "model": selected_model,
        "prompt": selected_prompt,
        "glossary_terms": selected_glossary_terms,
        "raw_text": raw_text,
        "corrected_text": corrected_text,
        "chunks": [
            {
                "index": chunk.index,
                "raw_text": chunk.raw_text,
                "corrected_text": chunk.corrected_text,
                "change_notes": chunk.notes,
                "needs_human_review": chunk.needs_human_review,
                "parse_error": chunk.parse_error,
            }
            for chunk in reviewed_chunks
        ],
    }
