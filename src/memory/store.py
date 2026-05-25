"""
store.py — MemoryStore

Facade that composes ShortTermMemory and LongTermMemory into a single
coherent API used by the rest of ClawBro.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from .long_term import LongTermMemory
from .short_term import ShortTermMemory
from . import init_db


_DEFAULT_DB = Path.home() / ".clawbro" / "memory.db"


class MemoryStore:
    """Unified memory facade for ClawBro agents."""

    def __init__(self, session_id: str, db_path: str | None = None) -> None:
        resolved = Path(db_path) if db_path else _DEFAULT_DB
        resolved.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(resolved), check_same_thread=False)
        # Enable WAL for better concurrent access
        self._conn.execute("PRAGMA journal_mode=WAL")
        # Enforce foreign-key constraints
        self._conn.execute("PRAGMA foreign_keys=ON")

        init_db(str(resolved), conn=self._conn)

        self._short = ShortTermMemory(session_id, self._conn)
        self._long = LongTermMemory(self._conn)
        self.session_id = session_id

    # ------------------------------------------------------------------
    # Short-term (session-scoped)
    # ------------------------------------------------------------------

    def add_turn(self, role: str, content: str) -> None:
        """Add a conversation turn to the current session."""
        self._short.add_turn(role, content)

    def get_history(self, max_tokens: int = 8000) -> list[dict[str, Any]]:
        """Return the conversation history, truncating the middle if needed.

        Algorithm (adapted from ZeroClaw history.rs):
        1. Estimate tokens as len(content) // 4.
        2. Always keep the first 2 turns (system context).
        3. Always keep the last 6 turns (recent context).
        4. Trim from the middle when over budget, inserting a
           "[...N turns truncated...]" placeholder at the trim point.
        """
        turns = self._short.get_history()
        n = len(turns)

        # Fast path: fits in budget
        total_tokens = sum(len(t["content"]) // 4 for t in turns)
        if total_tokens <= max_tokens:
            return [{"role": t["role"], "content": t["content"]} for t in turns]

        HEAD = 2  # always keep first N turns
        TAIL = 6  # always keep last M turns

        # If we have too few turns to split, return everything (graceful degradation)
        if n <= HEAD + TAIL:
            return [{"role": t["role"], "content": t["content"]} for t in turns]

        head_turns = turns[:HEAD]
        tail_turns = turns[n - TAIL:]
        middle_turns = turns[HEAD: n - TAIL]

        # Greedily drop middle turns from the *end of middle* until we fit
        kept_middle: list[dict] = list(middle_turns)
        while kept_middle:
            candidate = head_turns + kept_middle + tail_turns
            tok = sum(len(t["content"]) // 4 for t in candidate)
            if tok <= max_tokens:
                break
            kept_middle.pop()  # drop the last middle turn

        trimmed_count = len(middle_turns) - len(kept_middle)

        result: list[dict[str, Any]] = []
        result.extend({"role": t["role"], "content": t["content"]} for t in head_turns)
        result.extend({"role": t["role"], "content": t["content"]} for t in kept_middle)
        if trimmed_count > 0:
            result.append(
                {
                    "role": "system",
                    "content": f"[...{trimmed_count} turns truncated...]",
                }
            )
        result.extend({"role": t["role"], "content": t["content"]} for t in tail_turns)
        return result

    def clear_session(self) -> None:
        """Wipe the current session's in-memory buffer and DB rows."""
        self._short.clear_session()

    # ------------------------------------------------------------------
    # Long-term (persistent, cross-session)
    # ------------------------------------------------------------------

    def save(self, key: str, value: str, metadata: dict | None = None) -> None:
        """Persist a key/value pair to long-term memory."""
        self._long.save(key, value, metadata)

    def recall(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search long-term memory using FTS5, returning up to *limit* results."""
        return self._long.recall(query, limit)

    def delete(self, key: str) -> bool:
        """Remove a key from long-term memory. Returns True if found."""
        return self._long.delete(key)

    def list_keys(self, prefix: str = "") -> list[str]:
        """List all long-term memory keys, optionally filtered by prefix."""
        return self._long.list_keys(prefix)

    # ------------------------------------------------------------------
    # "learn" convenience command
    # ------------------------------------------------------------------

    def learn(self, text: str) -> str:
        """Parse *text* to extract a key/value pair and save it.

        Simple keyword-extraction heuristics (no Claude call required):
        - Strips common preambles like "remember that", "note that", etc.
        - Splits on ": ", " is ", " = ", " are " to separate key from value.
        - Normalises the key to snake_case.

        Returns a confirmation string.
        """
        key, value = self._parse_learn_text(text)
        self.save(key, value)
        return f"Remembered: '{key}' = '{value}'"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_learn_text(text: str) -> tuple[str, str]:
        """Extract (key, value) from a natural-language learn instruction."""
        # Strip common preamble phrases
        preambles = [
            r"^remember\s+that\s+",
            r"^note\s+that\s+",
            r"^the\s+",
            r"^remember\s+",
            r"^store\s+that\s+",
            r"^keep\s+in\s+mind\s+that\s+",
        ]
        normalised = text.strip().rstrip(".!?")
        for pat in preambles:
            normalised = re.sub(pat, "", normalised, flags=re.IGNORECASE)

        # Try splitting on common key-value separators
        for sep in (":", " = ", " is ", " are ", " -> ", " => "):
            if sep in normalised:
                parts = normalised.split(sep, 1)
                raw_key = parts[0].strip()
                value = parts[1].strip()
                key = _to_snake_case(raw_key)
                return key, value

        # Fallback: use the whole (cleaned) text as value, derive key from first words
        words = normalised.split()
        key_words = words[:4] if len(words) > 4 else words
        key = _to_snake_case(" ".join(key_words))
        value = normalised
        return key, value

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_snake_case(text: str) -> str:
    """Convert arbitrary text to a safe snake_case identifier."""
    # Lower-case
    s = text.lower()
    # Replace non-alphanumeric runs with underscores
    s = re.sub(r"[^a-z0-9]+", "_", s)
    # Strip leading/trailing underscores
    s = s.strip("_")
    return s or "memory_key"
