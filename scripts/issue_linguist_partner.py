#!/usr/bin/env python3
"""Issue KreyAI Linguist Partner licenses through the protected production API."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_API_BASE = "https://kreyai-api-98057750771.us-central1.run.app"


def issue(*, api_base: str, api_key: str, email: str, name: str, cohort: str, products: list[str], resend: bool) -> dict:
    payload = json.dumps(
        {
            "email": email,
            "name": name or None,
            "cohort": cohort,
            "products": products,
            "resend": resend,
        }
    ).encode("utf-8")
    request = Request(
        f"{api_base.rstrip('/')}/ops/licenses/linguist-partner",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"License service returned {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach the license service: {exc.reason}") from exc


def participants(args) -> list[dict[str, str]]:
    if args.csv:
        with Path(args.csv).open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        if not rows or "email" not in (rows[0].keys() if rows else []):
            raise ValueError("CSV must contain an email column. A name column is optional.")
        return [{"email": str(row.get("email") or "").strip(), "name": str(row.get("name") or "").strip()} for row in rows]
    return [{"email": args.email, "name": args.name or ""}]


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue complimentary KreyAI Linguist Partner licenses.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--email", help="Participant email address.")
    source.add_argument("--csv", help="CSV containing email and optional name columns.")
    parser.add_argument("--name", default="", help="Participant name when using --email.")
    parser.add_argument("--cohort", default="2026", help="Program cohort label.")
    parser.add_argument("--products", default="atelier,dekk", help="Comma-separated products: atelier,dekk.")
    parser.add_argument("--resend", action="store_true", help="Resend existing licenses instead of creating duplicates.")
    parser.add_argument("--api-base", default=os.getenv("KREYAI_API_BASE_URL", DEFAULT_API_BASE))
    args = parser.parse_args()

    api_key = os.getenv("KREYAI_OPS_API_KEY", "").strip()
    if not api_key:
        parser.error("KREYAI_OPS_API_KEY is required in the environment.")
    products = [value.strip().lower() for value in args.products.split(",") if value.strip()]

    failures = 0
    for participant in participants(args):
        email = participant["email"]
        if not email:
            print("Skipped a row with no email.", file=sys.stderr)
            failures += 1
            continue
        try:
            result = issue(
                api_base=args.api_base,
                api_key=api_key,
                email=email,
                name=participant["name"],
                cohort=args.cohort,
                products=products,
                resend=args.resend,
            )
            issued = [product for product, data in result.get("products", {}).items() if data.get("issued")]
            status = f"issued {', '.join(issued)}" if issued else "already issued"
            print(f"{email}: {status}; email sent={bool(result.get('email_sent'))}")
        except Exception as exc:
            failures += 1
            print(f"{email}: failed: {exc}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
