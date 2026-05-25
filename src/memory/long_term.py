"""
long_term.py — LongTermMemory

SQLite-backed persistent key/value store with FTS5 full-text search.
The schema (tables, virtual table, triggers) is created externally via
init_db(); this class only performs DML operations.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any


class LongTermMemory:
    """Persistent memory store with FTS5 recall capability."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, key: str, value: str, metadata: dict | None = None) -> None:
        """Insert or replace a key/value pair.

        The FTS5 virtual table is kept in sync automatically by the
        ltm_fts_insert / ltm_fts_update triggers defined in init_db().
        """
        meta_json = json.dumps(metadata or {})
        now = time.time()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO long_term_memory (key, value, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value      = excluded.value,
                    metadata   = excluded.metadata,
                    updated_at = excluded.updated_at
                """,
                (key, value, meta_json, now, now),
            )

    def recall(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Full-text search over long_term_memory, ranked by relevance.

        Returns a list of dicts with keys: key, value, metadata, created_at, updated_at.
        Falls back to a LIKE search when the FTS query returns no results (e.g. very
        short or non-word tokens that FTS5 ignores).
        """
        cursor = self._conn.execute(
            """
            SELECT ltm.key, ltm.value, ltm.metadata, ltm.created_at, ltm.updated_at
            FROM long_term_memory_fts
            JOIN long_term_memory ltm ON long_term_memory_fts.rowid = ltm.rowid
            WHERE long_term_memory_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        )
        rows = cursor.fetchall()

        # Fallback: LIKE search on key and value
        if not rows:
            like_pat = f"%{query}%"
            cursor = self._conn.execute(
                """
                SELECT key, value, metadata, created_at, updated_at
                FROM long_term_memory
                WHERE key LIKE ? OR value LIKE ?
                LIMIT ?
                """,
                (like_pat, like_pat, limit),
            )
            rows = cursor.fetchall()

        return [self._row_to_dict(row) for row in rows]

    def delete(self, key: str) -> bool:
        """Delete a key from long_term_memory (FTS5 sync via trigger).

        Returns True if a row was deleted, False if the key did not exist.
        """
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM long_term_memory WHERE key = ?", (key,)
            )
        return cursor.rowcount > 0

    def list_keys(self, prefix: str = "") -> list[str]:
        """Return all keys that start with *prefix* (empty string = all keys)."""
        like_pat = f"{prefix}%" if prefix else "%"
        cursor = self._conn.execute(
            "SELECT key FROM long_term_memory WHERE key LIKE ? ORDER BY key",
            (like_pat,),
        )
        return [row[0] for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: tuple) -> dict[str, Any]:
        key, value, metadata_json, created_at, updated_at = row
        try:
            metadata = json.loads(metadata_json or "{}")
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        return {
            "key": key,
            "value": value,
            "metadata": metadata,
            "created_at": created_at,
            "updated_at": updated_at,
        }
