"""
memory/__init__.py

Public exports for the ClawBro memory subsystem.

Usage
-----
    from memory import MemoryStore, init_db

    init_db("~/.clawbro/memory.db")  # idempotent – safe to call multiple times
    store = MemoryStore(session_id="abc123")
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


__all__ = ["MemoryStore", "init_db"]


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
-- Conversation history
CREATE TABLE IF NOT EXISTS conversation_turns (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT    NOT NULL,
    role       TEXT    NOT NULL CHECK(role IN ('user', 'assistant', 'tool', 'system')),
    content    TEXT    NOT NULL,
    timestamp  REAL    NOT NULL,
    created_at REAL    DEFAULT (unixepoch('now', 'subsec'))
);
CREATE INDEX IF NOT EXISTS idx_turns_session
    ON conversation_turns(session_id, timestamp);

-- Long-term memory
CREATE TABLE IF NOT EXISTS long_term_memory (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    metadata   TEXT DEFAULT '{}',
    created_at REAL DEFAULT (unixepoch('now', 'subsec')),
    updated_at REAL DEFAULT (unixepoch('now', 'subsec'))
);

-- FTS5 for long-term search
CREATE VIRTUAL TABLE IF NOT EXISTS long_term_memory_fts
    USING fts5(key, value, content='long_term_memory', content_rowid='rowid');

-- Keep FTS5 in sync
CREATE TRIGGER IF NOT EXISTS ltm_fts_insert AFTER INSERT ON long_term_memory BEGIN
    INSERT INTO long_term_memory_fts(rowid, key, value)
        VALUES (new.rowid, new.key, new.value);
END;

CREATE TRIGGER IF NOT EXISTS ltm_fts_delete BEFORE DELETE ON long_term_memory BEGIN
    INSERT INTO long_term_memory_fts(long_term_memory_fts, rowid, key, value)
        VALUES ('delete', old.rowid, old.key, old.value);
END;

CREATE TRIGGER IF NOT EXISTS ltm_fts_update AFTER UPDATE ON long_term_memory BEGIN
    INSERT INTO long_term_memory_fts(long_term_memory_fts, rowid, key, value)
        VALUES ('delete', old.rowid, old.key, old.value);
    INSERT INTO long_term_memory_fts(rowid, key, value)
        VALUES (new.rowid, new.key, new.value);
END;
"""


def init_db(db_path: str, conn: sqlite3.Connection | None = None) -> None:
    """Create all tables, indexes, virtual tables, and triggers.

    Idempotent — all DDL statements use IF NOT EXISTS / CREATE TRIGGER IF NOT EXISTS,
    so it is safe to call multiple times on the same database.

    Parameters
    ----------
    db_path:
        Path to the SQLite file.  The parent directory is created if absent.
    conn:
        Optional existing connection.  When provided *db_path* is still used to
        ensure the directory exists but a new connection is NOT opened.
    """
    resolved = Path(db_path).expanduser()
    resolved.parent.mkdir(parents=True, exist_ok=True)

    _conn = conn or sqlite3.connect(str(resolved))
    try:
        # executescript commits any open transaction first then runs statements
        # separated by semicolons — ideal for DDL blocks.
        _conn.executescript(_SCHEMA_SQL)
    finally:
        # Only close the connection if we opened it ourselves.
        if conn is None:
            _conn.close()


# ---------------------------------------------------------------------------
# Deferred import to avoid circular deps (store imports init_db from here)
# ---------------------------------------------------------------------------

from .store import MemoryStore  # noqa: E402  (must come after init_db definition)
