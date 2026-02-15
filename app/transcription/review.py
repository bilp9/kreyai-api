# app/transcription/review.py
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Dict

from app.transcription.promotion import (
    approve_candidate,
    reject_candidate,
    defer_candidate,
)

BASE_DIR = Path(__file__).parent
CANDIDATES_FILE = BASE_DIR / "candidates.json"


# ----------------------------
# Utilities
# ----------------------------

def load_candidates() -> List[Dict]:
    if not CANDIDATES_FILE.exists():
        print("ℹ️ No candidates file found.")
        return []

    with open(CANDIDATES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    return [c for c in data if c.get("status") == "pending"]


def save_candidates(all_candidates: List[Dict]) -> None:
    with open(CANDIDATES_FILE, "w", encoding="utf-8") as f:
        json.dump(all_candidates, f, indent=2, ensure_ascii=False)


def load_all_candidates() -> List[Dict]:
    if not CANDIDATES_FILE.exists():
        return []
    with open(CANDIDATES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def prompt_action() -> str:
    print("\nActions:")
    print(" [a] approve")
    print(" [r] reject")
    print(" [d] defer")
    print(" [s] skip")
    print(" [q] quit")
    return input("> ").strip().lower()


def show_candidate(cand: Dict, idx: int, total: int) -> None:
    print("\n" + "=" * 60)
    print(f"[{idx}/{total}] Candidate: {cand.get('id')}")
    print(f"Type:        {cand.get('type')}")
    print(f"Raw:         {cand.get('raw')}")
    print(f"Proposed:    {cand.get('proposed')}")
    print(f"Confidence:  {cand.get('confidence')}")
    print(f"Occurrences: {cand.get('occurrences')}")

    print("\nContexts:")
    for ctx in cand.get("contexts", []):
        print(f" • {ctx}")


# ----------------------------
# Review Loop
# ----------------------------

def review_loop() -> None:
    all_candidates = load_all_candidates()
    pending = [c for c in all_candidates if c.get("status") == "pending"]

    if not pending:
        print("✅ No pending candidates to review.")
        return

    total = len(pending)

    print("\n🧠 KREYAI — Feedback Review")
    print(f"Pending candidates: {total}")

    for idx, cand in enumerate(pending, start=1):
        show_candidate(cand, idx, total)

        action = prompt_action()

        if action == "a":
            approve_candidate(cand)
            cand["status"] = "approved"
            print("✅ Approved")

        elif action == "r":
            reject_candidate(cand)
            cand["status"] = "rejected"
            print("❌ Rejected")

        elif action == "d":
            defer_candidate(cand)
            cand["status"] = "deferred"
            print("⏸ Deferred")

        elif action == "s":
            print("⏭ Skipped")
            continue

        elif action == "q":
            print("👋 Exiting review.")
            break

        else:
            print("⚠ Invalid input, skipping.")
            continue

    save_candidates(all_candidates)
    print("\n💾 Review state saved.")


# ----------------------------
# Entrypoint
# ----------------------------

if __name__ == "__main__":
    try:
        review_loop()
    except KeyboardInterrupt:
        print("\n🛑 Review interrupted.")
        sys.exit(0)
