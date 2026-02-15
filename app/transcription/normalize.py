from __future__ import annotations

import re
import unicodedata
from typing import List, Tuple, Pattern, Optional, Dict, Any

from app.transcription.observability import PipelineMetrics

# -------------------------------------------------
# Rule definition
# -------------------------------------------------
Rule = Tuple[str, Pattern[str], str]  
# (rule_id, compiled_pattern, replacement)


def _compile(p: str) -> Pattern[str]:
    return re.compile(p, flags=re.IGNORECASE)


_COMBINING_RE = re.compile(r"[\u0300-\u036f]")


# -------------------------------------------------
# A2.5 — Mechanical cleanup (ALWAYS SAFE)
# -------------------------------------------------
def _strip_unicode_noise(text: str) -> str:
    t = unicodedata.normalize("NFKD", text)
    t = _COMBINING_RE.sub("", t)
    return t.replace("’", "'")


A25_RULES: List[Rule] = [
    ("A25.levae_leve", _compile(r"\blevae\b"), "leve"),
    ("A25.bezoen_bezwen", _compile(r"\bbezoen\b"), "bezwen"),
    ("A25.assizeh_sizer", _compile(r"\bassizeh\b"), "a sizè"),
]


# -------------------------------------------------
# A2 — SAFE normalization (never gated)
# -------------------------------------------------
A2_RULES: List[Rule] = [
    ("A2.apmache_ap_mache", _compile(r"\bapmach[eé]\b"), "ap mache"),
]


# -------------------------------------------------
# A3 — RESTRICTED rules
# (high confidence, low risk)
# -------------------------------------------------
A3_RESTRICTED_RULES: List[Rule] = [
    ("A3r.tojou_toujou", _compile(r"\btojou\b"), "toujou"),
    ("A3r.pa_jam_pa_janm", _compile(r"\bpa\s*jam\b"), "pa janm"),
    ("A3r.ap_plikasyon_aplikasyon", _compile(r"\bap\s*plikasyon\b"), "aplikasyon"),
    ("A3r.si_si_si", _compile(r"\bsi\s+si\b"), "si"),
]


# -------------------------------------------------
# A3 — FULL rules
# (riskier, HT-dominant only)
# -------------------------------------------------
A3_FULL_RULES: List[Rule] = [
    ("A3f.buon_bon", _compile(r"\bbuon\b"), "bon"),
    ("A3f.p_a_le_pale", _compile(r"\bp\s*a\s*le\b"), "pale"),
    ("A3f.un_pale_ann_pale", _compile(r"\bun\s+pale\b"), "ann pale"),
    ("A3f.debi_depi", _compile(r"\bdeb[iy]\b"), "depi"),
    ("A3f.moin_mwen", _compile(r"\bmoin\b"), "mwen"),
    ("A3f.kek_kek", _compile(r"\bkek\b"), "kèk"),
] + A3_RESTRICTED_RULES  # full includes restricted


# -------------------------------------------------
# Public API
# -------------------------------------------------
def normalize_creole(
    text: str,
    *,
    a3_mode: str = "none",  # "none" | "restricted" | "full"
    metrics: Optional[PipelineMetrics] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Deterministic Creole normalization.

    Returns:
      (normalized_text, a3_events)

    a3_events = [
      {
        "rule_id": "...",
        "before": "...",
        "after": "...",
        "mode": "restricted|full"
      }
    ]
    """
    if not text:
        return text, []

    out = _strip_unicode_noise(text)
    events: List[Dict[str, Any]] = []

    # ----------------------------
    # A2.5 — mechanical cleanup
    # ----------------------------
    for rule_id, pattern, repl in A25_RULES:
        new_out = pattern.sub(repl, out)
        if new_out != out:
            out = new_out

    # ----------------------------
    # A2 — safe rules
    # ----------------------------
    for rule_id, pattern, repl in A2_RULES:
        new_out = pattern.sub(repl, out)
        if new_out != out:
            out = new_out

    # ----------------------------
    # A3 — gated rules
    # ----------------------------
    if a3_mode == "restricted":
        rules = A3_RESTRICTED_RULES
    elif a3_mode == "full":
        rules = A3_FULL_RULES
    else:
        rules = []

    for rule_id, pattern, repl in rules:
        new_out = pattern.sub(repl, out)
        if new_out != out:
            events.append(
                {
                    "rule_id": rule_id,
                    "before": out,
                    "after": new_out,
                    "mode": a3_mode,
                }
            )
            out = new_out

    # ----------------------------
    # Observability (safe)
    # ----------------------------
    if metrics is not None and hasattr(metrics, "bump"):
        metrics.bump(f"normalize_creole.a3_{a3_mode}")

    return out, events
