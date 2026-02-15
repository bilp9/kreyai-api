from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional, Literal, List


# =========================================================
# Promotion thresholds (TUNED)
# =========================================================

MIN_FIRES_EXPERIMENTAL = 10
MIN_FIRES_RESTRICTED   = 18
MIN_FIRES_FULL         = 30

MAX_REVERSAL_RATE_RESTRICTED = 0.15
MAX_REVERSAL_RATE_FULL       = 0.08
DISABLE_REVERSAL_RATE        = 0.25


# =========================================================
# Paths
# =========================================================

# Raw A3 events (append-only, audit / replay)
A3_LOG_PATH = Path(__file__).parent / "data" / "a3_events.jsonl"

# Aggregated promotion DB (authoritative state)
DEFAULT_PATH = Path(__file__).parent / "data" / "a3_promotion.json"


# =========================================================
# Types
# =========================================================

PromotionState = Literal["experimental", "restricted", "full", "disabled"]


@dataclass
class RuleStats:
    rule_id: str

    fires_total: int = 0
    fires_restricted: int = 0
    fires_full: int = 0

    reversals_total: int = 0

    akademi_valid: int = 0
    akademi_invalid: int = 0

    # Speaker-level feedback (future UI / review loop)
    speaker_accepts: int = 0
    speaker_rejects: int = 0

    state: PromotionState = "experimental"
    updated_at: float = 0.0


# =========================================================
# Persistence helpers
# =========================================================

def _now() -> float:
    return time.time()


def load_promotion_db(path: Path = DEFAULT_PATH) -> Dict[str, RuleStats]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: Dict[str, RuleStats] = {}
    for rid, payload in raw.items():
        out[rid] = RuleStats(**payload)
    return out


def save_promotion_db(db: Dict[str, RuleStats], path: Path = DEFAULT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    raw = {rid: asdict(stats) for rid, stats in db.items()}
    tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# =========================================================
# Raw event logging (engine → promotion bridge)
# =========================================================

def record_a3_events(events: List[dict]) -> None:
    """
    Append raw A3 events (engine-level) for audit, replay,
    and offline analysis.
    """
    if not events:
        return

    A3_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with A3_LOG_PATH.open("a", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")


# =========================================================
# Scoring + State Machine
# =========================================================

def rule_score(stats: RuleStats) -> float:
    fires = stats.fires_total
    rev = stats.reversals_total

    accept_rate = max(0.0, (fires - rev) / max(1, fires))   # 0..1
    reversal_rate = rev / max(1, fires)                     # 0..1

    ak_total = stats.akademi_valid + stats.akademi_invalid
    akademi_signal = (
        (stats.akademi_valid - stats.akademi_invalid) / ak_total
        if ak_total > 0 else 0.0
    )  # -1..1

    sp_total = stats.speaker_accepts + stats.speaker_rejects
    speaker_signal = (
        (stats.speaker_accepts - stats.speaker_rejects) / sp_total
        if sp_total > 0 else 0.0
    )  # -1..1

    return (
        3.0 * accept_rate
        - 5.0 * reversal_rate
        + 1.2 * akademi_signal
        + 0.5 * speaker_signal
    )


def next_state(stats: RuleStats) -> PromotionState:
    fires = stats.fires_total
    rev_rate = stats.reversals_total / max(1, fires)
    score = rule_score(stats)

    # Immediate safety cutoff
    if fires >= 12 and rev_rate >= DISABLE_REVERSAL_RATE:
        return "disabled"

    if fires < MIN_FIRES_EXPERIMENTAL:
        return "experimental"

    if (
        fires >= MIN_FIRES_FULL
        and rev_rate < MAX_REVERSAL_RATE_FULL
        and score >= 2.8
        and (stats.akademi_valid - stats.akademi_invalid) >= 2
    ):
        return "full"

    if (
        fires >= MIN_FIRES_RESTRICTED
        and rev_rate < MAX_REVERSAL_RATE_RESTRICTED
        and score >= 1.6
    ):
        return "restricted"

    return "experimental"


# =========================================================
# Mutation helpers (called by engine / review tools)
# =========================================================

def _get(db: Dict[str, RuleStats], rule_id: str) -> RuleStats:
    if rule_id not in db:
        db[rule_id] = RuleStats(rule_id=rule_id)
    return db[rule_id]


def record_fire(
    db: Dict[str, RuleStats],
    *,
    rule_id: str,
    mode: Literal["restricted", "full"],
) -> None:
    st = _get(db, rule_id)
    st.fires_total += 1
    if mode == "restricted":
        st.fires_restricted += 1
    else:
        st.fires_full += 1
    st.updated_at = _now()
    st.state = next_state(st)


def record_reversal(
    db: Dict[str, RuleStats],
    *,
    rule_id: str,
) -> None:
    st = _get(db, rule_id)
    st.reversals_total += 1
    st.updated_at = _now()
    st.state = next_state(st)


def record_akademi_validation(
    db: Dict[str, RuleStats],
    *,
    rule_id: str,
    valid: bool,
) -> None:
    st = _get(db, rule_id)
    if valid:
        st.akademi_valid += 1
    else:
        st.akademi_invalid += 1
    st.updated_at = _now()
    st.state = next_state(st)


def record_speaker_vote(
    db: Dict[str, RuleStats],
    *,
    rule_id: str,
    accepted: bool,
) -> None:
    st = _get(db, rule_id)
    if accepted:
        st.speaker_accepts += 1
    else:
        st.speaker_rejects += 1
    st.updated_at = _now()
    st.state = next_state(st)
