"""
short_term.py — ShortTermMemory

In-memory ring buffer (collections.deque) holding conversation turns for the
current session, with concurrent SQLite persistence.
"""

from __future__ import annotations

import sqlite3
import time
from collections import deque
from typing import Any


class ShortTermMemory:
    """Session-scoped conversation buffer backed by SQLite for durability."""

    MAX_BUFFER_SIZE: int = 50

    def __init__(
        self,
        session_id: str,
        conn: sqlite3.Connection,
        max_size: int = MAX_BUFFER_SIZE,
    ) -> None:
        self.session_id = session_id
        self._conn = conn
        self._max_size = max_size
        # Ring buffer: each element is {"role": str, "content": str, "timestamp": float}
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_size)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_turn(self, role: str, content: str) -> None:
        """Append a turn to the ring buffer and persist it to SQLite."""
        ts = time.time()
        turn: dict[str, Any] = {"role": role, "content": content, "timestamp": ts}
        self._buffer.append(turn)
        self._persist(role, content, ts)

    def get_history(self) -> list[dict[str, Any]]:
        """Return the current buffer as a plain list (oldest first)."""
        return list(self._buffer)

    def clear_session(self) -> None:
        """Clear the in-memory buffer and remove this session's DB rows."""
        self._buffer.clear()
        with self._conn:
            self._conn.execute(
                "DELETE FROM conversation_turns WHERE session_id = ?",
                (self.session_id,),
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _persist(self, role: str, content: str, timestamp: float) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO conversation_turns (session_id, role, content, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (self.session_id, role, content, timestamp),
            )
