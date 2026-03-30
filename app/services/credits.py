from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from google.cloud import firestore


db = firestore.Client()
ACCOUNTS_COLLECTION = "credit_accounts"
LEDGER_COLLECTION = "credit_ledger"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_billing_email(email: str) -> str:
    return str(email or "").strip().lower()


@dataclass
class CreditAccount:
    email: str
    balance_minutes: int
    total_purchased_minutes: int
    total_consumed_minutes: int
    total_refunded_minutes: int
    stripe_customer_id: Optional[str]
    updated_at: Optional[str]


def _account_doc(email: str):
    normalized = normalize_billing_email(email)
    return db.collection(ACCOUNTS_COLLECTION).document(normalized)


def get_credit_account(email: str) -> CreditAccount:
    normalized = normalize_billing_email(email)
    snap = _account_doc(normalized).get()
    data = snap.to_dict() or {}
    return CreditAccount(
        email=normalized,
        balance_minutes=int(data.get("balance_minutes") or 0),
        total_purchased_minutes=int(data.get("total_purchased_minutes") or 0),
        total_consumed_minutes=int(data.get("total_consumed_minutes") or 0),
        total_refunded_minutes=int(data.get("total_refunded_minutes") or 0),
        stripe_customer_id=data.get("stripe_customer_id"),
        updated_at=data.get("updated_at"),
    )


def get_credit_balance_minutes(email: str) -> int:
    return get_credit_account(email).balance_minutes


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
