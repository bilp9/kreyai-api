from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Dict, Literal, Optional

from google.cloud import firestore


db = firestore.Client()
ACCOUNTS_COLLECTION = "credit_accounts"
LEDGER_COLLECTION = "credit_ledger"
STARTER_GRANT_MINUTES = 30
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_billing_email(email: str) -> str:
    return str(email or "").strip().lower()


def is_valid_billing_email(email: str) -> bool:
    normalized = normalize_billing_email(email)
    return bool(normalized and EMAIL_PATTERN.match(normalized))


@dataclass
class CreditAccount:
    email: str
    balance_minutes: int
    total_purchased_minutes: int
    total_granted_minutes: int
    total_consumed_minutes: int
    total_refunded_minutes: int
    stripe_customer_id: Optional[str]
    updated_at: Optional[str]


@dataclass
class CreditLedgerEntry:
    id: str
    email: str
    entry_type: str
    delta_minutes: int
    balance_after_minutes: int
    source: str
    description: str
    metadata: Dict[str, Any]
    created_at: Optional[str]


def _account_doc(email: str):
    normalized = normalize_billing_email(email)
    return db.collection(ACCOUNTS_COLLECTION).document(normalized)


def get_credit_account(email: str) -> CreditAccount:
    normalized = normalize_billing_email(email)
    if not is_valid_billing_email(normalized):
        raise ValueError("email is required")
    snap = _account_doc(normalized).get()
    data = snap.to_dict() or {}
    return CreditAccount(
        email=normalized,
        balance_minutes=int(data.get("balance_minutes") or 0),
        total_purchased_minutes=int(data.get("total_purchased_minutes") or 0),
        total_granted_minutes=int(data.get("total_granted_minutes") or 0),
        total_consumed_minutes=int(data.get("total_consumed_minutes") or 0),
        total_refunded_minutes=int(data.get("total_refunded_minutes") or 0),
        stripe_customer_id=data.get("stripe_customer_id"),
        updated_at=data.get("updated_at"),
    )


def get_credit_balance_minutes(email: str) -> int:
    return get_credit_account(email).balance_minutes


def list_credit_ledger(email: str, *, limit: int = 50) -> list[CreditLedgerEntry]:
    normalized = normalize_billing_email(email)
    if not normalized:
        raise ValueError("email is required")

    query = db.collection(LEDGER_COLLECTION).where("email", "==", normalized)

    entries: list[CreditLedgerEntry] = []
    for snap in query.stream():
        data = snap.to_dict() or {}
        entries.append(
            CreditLedgerEntry(
                id=snap.id,
                email=normalized,
                entry_type=str(data.get("entry_type") or ""),
                delta_minutes=int(data.get("delta_minutes") or 0),
                balance_after_minutes=int(data.get("balance_after_minutes") or 0),
                source=str(data.get("source") or ""),
                description=str(data.get("description") or ""),
                metadata=data.get("metadata") or {},
                created_at=data.get("created_at"),
            )
        )

    entries.sort(key=lambda entry: entry.created_at or "", reverse=True)
    return entries[: max(1, min(int(limit or 50), 100))]


def ensure_starter_credit_grant(email: str) -> Dict[str, Any]:
    normalized = normalize_billing_email(email)
    if not is_valid_billing_email(normalized):
        raise ValueError("email is required")
    if STARTER_GRANT_MINUTES <= 0:
        return {"applied": False, "balance_minutes": get_credit_balance_minutes(normalized)}

    txn = db.transaction()
    account_ref = _account_doc(normalized)
    ledger_ref = _ledger_doc(f"starter_grant:{normalized}")

    @firestore.transactional
    def _apply(transaction: firestore.Transaction) -> Dict[str, Any]:
        ledger_snap = ledger_ref.get(transaction=transaction)
        if ledger_snap.exists:
            existing = ledger_snap.to_dict() or {}
            return {
                "applied": False,
                "balance_minutes": int(existing.get("balance_after_minutes") or 0),
            }

        account_snap = account_ref.get(transaction=transaction)
        account = account_snap.to_dict() or {}
        has_existing_activity = any(
            int(account.get(field) or 0) > 0
            for field in (
                "balance_minutes",
                "total_purchased_minutes",
                "total_granted_minutes",
                "total_consumed_minutes",
                "total_refunded_minutes",
            )
        ) or bool(account.get("stripe_customer_id"))

        if has_existing_activity:
            return {
                "applied": False,
                "balance_minutes": int(account.get("balance_minutes") or 0),
            }

        next_balance = STARTER_GRANT_MINUTES
        account_update = {
            "email": normalized,
            "balance_minutes": next_balance,
            "total_purchased_minutes": int(account.get("total_purchased_minutes") or 0),
            "total_granted_minutes": int(account.get("total_granted_minutes") or 0) + STARTER_GRANT_MINUTES,
            "total_consumed_minutes": int(account.get("total_consumed_minutes") or 0),
            "total_refunded_minutes": int(account.get("total_refunded_minutes") or 0),
            "stripe_customer_id": account.get("stripe_customer_id"),
            "updated_at": _utcnow_iso(),
        }
        transaction.set(account_ref, account_update, merge=True)
        transaction.set(
            ledger_ref,
            {
                "email": normalized,
                "entry_type": "starter_grant",
                "delta_minutes": STARTER_GRANT_MINUTES,
                "balance_after_minutes": next_balance,
                "source": "starter_grant",
                "description": "One-time starter credit grant",
                "metadata": {"starter_grant_minutes": STARTER_GRANT_MINUTES},
                "created_at": _utcnow_iso(),
            },
        )
        return {"applied": True, "balance_minutes": next_balance}

    return _apply(txn)


def _ledger_doc(idempotency_key: str):
    return db.collection(LEDGER_COLLECTION).document(idempotency_key)


def add_credit_minutes(
    *,
    email: str,
    minutes: int,
    source: str,
    description: str,
    idempotency_key: str,
    metadata: Optional[Dict[str, Any]] = None,
    stripe_customer_id: Optional[str] = None,
) -> Dict[str, Any]:
    normalized = normalize_billing_email(email)
    minutes = max(0, int(minutes or 0))
    if not normalized:
        raise ValueError("email is required")
    if minutes <= 0:
        raise ValueError("minutes must be positive")

    txn = db.transaction()
    account_ref = _account_doc(normalized)
    ledger_ref = _ledger_doc(idempotency_key)

    @firestore.transactional
    def _apply(transaction: firestore.Transaction) -> Dict[str, Any]:
        ledger_snap = ledger_ref.get(transaction=transaction)
        if ledger_snap.exists:
            existing = ledger_snap.to_dict() or {}
            return {
                "applied": False,
                "balance_minutes": int(existing.get("balance_after_minutes") or 0),
            }

        account_snap = account_ref.get(transaction=transaction)
        account = account_snap.to_dict() or {}
        next_balance = int(account.get("balance_minutes") or 0) + minutes

        account_update = {
            "email": normalized,
            "balance_minutes": next_balance,
            "total_purchased_minutes": int(account.get("total_purchased_minutes") or 0) + minutes,
            "total_granted_minutes": int(account.get("total_granted_minutes") or 0),
            "total_consumed_minutes": int(account.get("total_consumed_minutes") or 0),
            "total_refunded_minutes": int(account.get("total_refunded_minutes") or 0),
            "stripe_customer_id": stripe_customer_id or account.get("stripe_customer_id"),
            "updated_at": _utcnow_iso(),
        }
        transaction.set(account_ref, account_update, merge=True)
        transaction.set(
            ledger_ref,
            {
                "email": normalized,
                "entry_type": "credit_purchase",
                "delta_minutes": minutes,
                "balance_after_minutes": next_balance,
                "source": source,
                "description": description,
                "metadata": metadata or {},
                "created_at": _utcnow_iso(),
            },
        )
        return {"applied": True, "balance_minutes": next_balance}

    return _apply(txn)


def consume_credit_minutes(
    *,
    email: str,
    minutes: int,
    idempotency_key: str,
    source: str,
    description: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized = normalize_billing_email(email)
    minutes = max(0, int(minutes or 0))
    if not normalized:
        raise ValueError("email is required")
    if minutes <= 0:
        raise ValueError("minutes must be positive")

    txn = db.transaction()
    account_ref = _account_doc(normalized)
    ledger_ref = _ledger_doc(idempotency_key)

    @firestore.transactional
    def _apply(transaction: firestore.Transaction) -> Dict[str, Any]:
        ledger_snap = ledger_ref.get(transaction=transaction)
        if ledger_snap.exists:
            existing = ledger_snap.to_dict() or {}
            return {
                "applied": False,
                "balance_minutes": int(existing.get("balance_after_minutes") or 0),
            }

        account_snap = account_ref.get(transaction=transaction)
        account = account_snap.to_dict() or {}
        balance = int(account.get("balance_minutes") or 0)
        if balance < minutes:
            raise ValueError("insufficient_credits")

        next_balance = balance - minutes
        account_update = {
            "email": normalized,
            "balance_minutes": next_balance,
            "total_purchased_minutes": int(account.get("total_purchased_minutes") or 0),
            "total_granted_minutes": int(account.get("total_granted_minutes") or 0),
            "total_consumed_minutes": int(account.get("total_consumed_minutes") or 0) + minutes,
            "total_refunded_minutes": int(account.get("total_refunded_minutes") or 0),
            "stripe_customer_id": account.get("stripe_customer_id"),
            "updated_at": _utcnow_iso(),
        }
        transaction.set(account_ref, account_update, merge=True)
        transaction.set(
            ledger_ref,
            {
                "email": normalized,
                "entry_type": "job_debit",
                "delta_minutes": -minutes,
                "balance_after_minutes": next_balance,
                "source": source,
                "description": description,
                "metadata": metadata or {},
                "created_at": _utcnow_iso(),
            },
        )
        return {"applied": True, "balance_minutes": next_balance}

    return _apply(txn)


def refund_credit_minutes(
    *,
    email: str,
    minutes: int,
    idempotency_key: str,
    source: str,
    description: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized = normalize_billing_email(email)
    minutes = max(0, int(minutes or 0))
    if not normalized:
        raise ValueError("email is required")
    if minutes <= 0:
        raise ValueError("minutes must be positive")

    txn = db.transaction()
    account_ref = _account_doc(normalized)
    ledger_ref = _ledger_doc(idempotency_key)

    @firestore.transactional
    def _apply(transaction: firestore.Transaction) -> Dict[str, Any]:
        ledger_snap = ledger_ref.get(transaction=transaction)
        if ledger_snap.exists:
            existing = ledger_snap.to_dict() or {}
            return {
                "applied": False,
                "balance_minutes": int(existing.get("balance_after_minutes") or 0),
            }

        account_snap = account_ref.get(transaction=transaction)
        account = account_snap.to_dict() or {}
        next_balance = int(account.get("balance_minutes") or 0) + minutes

        account_update = {
            "email": normalized,
            "balance_minutes": next_balance,
            "total_purchased_minutes": int(account.get("total_purchased_minutes") or 0),
            "total_granted_minutes": int(account.get("total_granted_minutes") or 0),
            "total_consumed_minutes": int(account.get("total_consumed_minutes") or 0),
            "total_refunded_minutes": int(account.get("total_refunded_minutes") or 0) + minutes,
            "stripe_customer_id": account.get("stripe_customer_id"),
            "updated_at": _utcnow_iso(),
        }
        transaction.set(account_ref, account_update, merge=True)
        transaction.set(
            ledger_ref,
            {
                "email": normalized,
                "entry_type": "job_refund",
                "delta_minutes": minutes,
                "balance_after_minutes": next_balance,
                "source": source,
                "description": description,
                "metadata": metadata or {},
                "created_at": _utcnow_iso(),
            },
        )
        return {"applied": True, "balance_minutes": next_balance}

    return _apply(txn)


def adjust_credit_minutes(
    *,
    email: str,
    minutes: int,
    action: Literal["grant", "refund", "debit"],
    idempotency_key: str,
    source: str,
    description: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized = normalize_billing_email(email)
    minutes = max(0, int(minutes or 0))
    if not normalized:
        raise ValueError("email is required")
    if minutes <= 0:
        raise ValueError("minutes must be positive")

    txn = db.transaction()
    account_ref = _account_doc(normalized)
    ledger_ref = _ledger_doc(idempotency_key)

    @firestore.transactional
    def _apply(transaction: firestore.Transaction) -> Dict[str, Any]:
        ledger_snap = ledger_ref.get(transaction=transaction)
        if ledger_snap.exists:
            existing = ledger_snap.to_dict() or {}
            return {
                "applied": False,
                "balance_minutes": int(existing.get("balance_after_minutes") or 0),
            }

        account_snap = account_ref.get(transaction=transaction)
        account = account_snap.to_dict() or {}
        balance = int(account.get("balance_minutes") or 0)
        signed_delta = -minutes if action == "debit" else minutes
        next_balance = balance + signed_delta

        if next_balance < 0:
            raise ValueError("insufficient_credits")

        total_granted_minutes = int(account.get("total_granted_minutes") or 0)
        total_consumed_minutes = int(account.get("total_consumed_minutes") or 0)
        total_refunded_minutes = int(account.get("total_refunded_minutes") or 0)

        if action == "grant":
            total_granted_minutes += minutes
        elif action == "refund":
            total_refunded_minutes += minutes
        elif action == "debit":
            total_consumed_minutes += minutes

        account_update = {
            "email": normalized,
            "balance_minutes": next_balance,
            "total_purchased_minutes": int(account.get("total_purchased_minutes") or 0),
            "total_granted_minutes": total_granted_minutes,
            "total_consumed_minutes": total_consumed_minutes,
            "total_refunded_minutes": total_refunded_minutes,
            "stripe_customer_id": account.get("stripe_customer_id"),
            "updated_at": _utcnow_iso(),
        }
        transaction.set(account_ref, account_update, merge=True)
        transaction.set(
            ledger_ref,
            {
                "email": normalized,
                "entry_type": f"manual_{action}",
                "delta_minutes": signed_delta,
                "balance_after_minutes": next_balance,
                "source": source,
                "description": description,
                "metadata": metadata or {},
                "created_at": _utcnow_iso(),
            },
        )
        return {"applied": True, "balance_minutes": next_balance}

    return _apply(txn)
