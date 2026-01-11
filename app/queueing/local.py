# app/queueing/local.py
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.constants import (
    QUEUE_DB_PATH,
    QUEUE_LEASE_SECONDS,
    QUEUE_MAX_ATTEMPTS,
)

UTC = timezone.utc


def _utc_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


@dataclass
class LocalSQLiteQueue:
    """
    Durable local queue using SQLite.

    States:
      - pending  : available for lease
      - leased   : currently leased by a worker
      - done     : completed successfully
      - failed   : permanently failed
    """

    db_path: str = QUEUE_DB_PATH

    def __post_init__(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS queue (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    leased_at TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON queue(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_leased_at ON queue(leased_at);")

    def enqueue(self, job_id: str) -> None:
        now = _utc_iso()
        with self._conn() as conn:
            # If job already exists and is not done/failed, keep it (idempotent enqueue).
            conn.execute(
                """
                INSERT INTO queue (job_id, status, created_at, leased_at, attempts, last_error)
                VALUES (?, 'pending', ?, NULL, 0, NULL)
                ON CONFLICT(job_id) DO UPDATE SET
                    status = CASE
                        WHEN queue.status IN ('done', 'failed') THEN queue.status
                        ELSE 'pending'
                    END,
                    last_error = NULL
                ;
                """,
                (job_id, now),
            )

    def _lease_expired(self, leased_at_iso: Optional[str]) -> bool:
        if not leased_at_iso:
            return False
        try:
            leased_at = datetime.fromisoformat(leased_at_iso)
        except Exception:
            return True
        age = (datetime.now(tz=UTC) - leased_at).total_seconds()
        return age >= QUEUE_LEASE_SECONDS

    def lease(self) -> Optional[str]:
        """
        Atomically lease one job:
        - prefer pending
        - also reclaim expired leases
        - enforce max attempts
        """
        now = _utc_iso()

        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE;")

            # 1) Find a pending job with attempts < max
            row = conn.execute(
                """
                SELECT job_id
                FROM queue
                WHERE status = 'pending'
                  AND attempts < ?
                ORDER BY created_at ASC
                LIMIT 1;
                """,
                (QUEUE_MAX_ATTEMPTS,),
            ).fetchone()

            # 2) If none pending, reclaim an expired lease
            if row is None:
                # We select leased jobs and reclaim if lease is expired
                leased_rows = conn.execute(
                    """
                    SELECT job_id, leased_at, attempts
                    FROM queue
                    WHERE status = 'leased'
                      AND attempts < ?
                    ORDER BY leased_at ASC
                    LIMIT 25;
                    """,
                    (QUEUE_MAX_ATTEMPTS,),
                ).fetchall()

                reclaim_id = None
                for r in leased_rows:
                    if self._lease_expired(r["leased_at"]):
                        reclaim_id = r["job_id"]
                        break

                if reclaim_id is None:
                    conn.execute("COMMIT;")
                    return None

                job_id = reclaim_id
            else:
                job_id = row["job_id"]

            # 3) Lease it (atomic update)
            updated = conn.execute(
                """
                UPDATE queue
                SET status = 'leased',
                    leased_at = ?,
                    attempts = attempts + 1
                WHERE job_id = ?
                  AND status IN ('pending', 'leased')
                  AND attempts < ?;
                """,
                (now, job_id, QUEUE_MAX_ATTEMPTS),
            ).rowcount

            conn.execute("COMMIT;")

            if updated == 1:
                return job_id
            return None

    def complete(self, job_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE queue
                SET status = 'done'
                WHERE job_id = ?;
                """,
                (job_id,),
            )

    def fail(self, job_id: str, reason: str) -> None:
        with self._conn() as conn:
            # Permanently fail the job at the queue level.
            conn.execute(
                """
                UPDATE queue
                SET status = 'failed',
                    last_error = ?
                WHERE job_id = ?;
                """,
                (reason[:500], job_id),
            )
