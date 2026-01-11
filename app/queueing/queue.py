# app/queueing/queue.py
import sqlite3
import time
from typing import Optional


class LocalSQLiteQueue:
    def __init__(self, path: str = "queue.db"):
        self.path = path
        self._init_db()

    def _conn(self):
        return sqlite3.connect(self.path, timeout=30, isolation_level=None)

    def _init_db(self):
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS queue (
                    job_id TEXT PRIMARY KEY,
                    status TEXT,
                    updated_at REAL
                )
                """
            )

    # -------------------------
    # Public API (CONTRACT)
    # -------------------------

    def enqueue(self, job_id: str):
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO queue (job_id, status, updated_at)
                VALUES (?, 'queued', ?)
                """,
                (job_id, time.time()),
            )

    def dequeue(self) -> Optional[str]:
        """
        Atomically claims ONE queued job and marks it as processing.
        """
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT job_id FROM queue
                WHERE status = 'queued'
                ORDER BY updated_at
                LIMIT 1
                """
            ).fetchone()

            if not row:
                return None

            job_id = row[0]

            conn.execute(
                """
                UPDATE queue
                SET status = 'processing', updated_at = ?
                WHERE job_id = ?
                """,
                (time.time(), job_id),
            )

            return job_id

    def complete(self, job_id: str):
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM queue WHERE job_id = ?",
                (job_id,),
            )

    def fail(self, job_id: str, reason: str):
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE queue
                SET status = 'failed', updated_at = ?
                WHERE job_id = ?
                """,
                (time.time(), job_id),
            )
