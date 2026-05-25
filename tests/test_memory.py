"""
test_memory.py — pytest test suite for the ClawBro memory subsystem.

All tests use a temporary SQLite file via pytest's tmp_path fixture so they
never touch the real ~/.clawbro/memory.db.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make sure the outputs/src directory is on the path so imports work regardless
# of how pytest is invoked.
_SRC = Path(__file__).parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest
from memory import MemoryStore, init_db  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def store(tmp_path: Path) -> MemoryStore:
    """Return a fresh MemoryStore backed by a temp database."""
    db_file = tmp_path / "test_memory.db"
    return MemoryStore(session_id="test-session", db_path=str(db_file))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestShortTermMemory:
    def test_add_and_get_history(self, store: MemoryStore) -> None:
        """Turns added via add_turn() should appear in get_history()."""
        store.add_turn("user", "Hello, ClawBro!")
        store.add_turn("assistant", "Hi there! How can I help you?")

        history = store.get_history()

        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello, ClawBro!"
        assert history[1]["role"] == "assistant"
        assert history[1]["content"] == "Hi there! How can I help you?"

    def test_history_truncation(self, store: MemoryStore) -> None:
        """Adding 60 turns with large content should trigger middle truncation."""
        # Each turn has ~4000 chars → ~1000 tokens; 60 turns = 60 000 tokens
        # With max_tokens=8000 and HEAD=2, TAIL=6 kept, the middle must be trimmed.
        big_content = "X" * 4000  # 4000 chars = 1000 estimated tokens

        for i in range(60):
            role = "user" if i % 2 == 0 else "assistant"
            store.add_turn(role, big_content)

        history = store.get_history(max_tokens=8000)

        # Verify a truncation placeholder exists somewhere in the middle
        placeholders = [
            t for t in history if "turns truncated" in t.get("content", "")
        ]
        assert placeholders, "Expected at least one truncation placeholder"

        # First 2 turns (HEAD) must be present
        full_turns = [t for t in history if "truncated" not in t.get("content", "")]
        assert len(full_turns) >= 8  # HEAD=2 + TAIL=6 + possibly some middle

        # The placeholder must appear between the head and tail sections
        placeholder_idx = history.index(placeholders[0])
        assert placeholder_idx >= 2, "Placeholder should not be in the HEAD section"

    def test_clear_session(self, store: MemoryStore) -> None:
        """clear_session() should empty the buffer."""
        store.add_turn("user", "Will this be cleared?")
        store.clear_session()
        assert store.get_history() == []

    def test_history_within_budget_unchanged(self, store: MemoryStore) -> None:
        """Small histories that fit in the token budget are returned as-is."""
        store.add_turn("user", "short")
        store.add_turn("assistant", "also short")
        history = store.get_history(max_tokens=8000)
        assert len(history) == 2
        placeholders = [t for t in history if "truncated" in t.get("content", "")]
        assert not placeholders


class TestLongTermMemory:
    def test_save_and_recall(self, store: MemoryStore) -> None:
        """A saved fact should be retrievable via FTS5 recall."""
        store.save("project_language", "Python", metadata={"source": "user"})
        store.save("project_framework", "FastAPI", metadata={"source": "user"})

        results = store.recall("Python")

        assert results, "recall() returned no results"
        keys = [r["key"] for r in results]
        assert "project_language" in keys

    def test_recall_returns_metadata(self, store: MemoryStore) -> None:
        """recall() results should include the metadata dict."""
        store.save("port", "8080", metadata={"category": "network"})
        results = store.recall("8080")
        assert results
        assert results[0]["metadata"].get("category") == "network"

    def test_delete(self, store: MemoryStore) -> None:
        """delete() should remove the key and return True; second delete returns False."""
        store.save("temp_key", "temp_value")
        assert store.delete("temp_key") is True
        assert store.delete("temp_key") is False  # already gone

        # Confirm it's truly gone from recall
        results = store.recall("temp_value")
        assert all(r["key"] != "temp_key" for r in results)

    def test_list_keys(self, store: MemoryStore) -> None:
        """list_keys() with a prefix should return only matching keys."""
        store.save("proj_name", "ClawBro")
        store.save("proj_version", "1.0.0")
        store.save("proj_port", "9000")
        store.save("user_name", "AP")

        proj_keys = store.list_keys(prefix="proj_")
        assert set(proj_keys) == {"proj_name", "proj_version", "proj_port"}

    def test_list_keys_no_prefix(self, store: MemoryStore) -> None:
        """list_keys() with no prefix should return all keys."""
        store.save("alpha", "1")
        store.save("beta", "2")
        all_keys = store.list_keys()
        assert "alpha" in all_keys
        assert "beta" in all_keys

    def test_save_overwrites_existing_key(self, store: MemoryStore) -> None:
        """Saving the same key twice should update the value, not duplicate."""
        store.save("my_key", "original")
        store.save("my_key", "updated")

        keys = store.list_keys(prefix="my_key")
        assert keys.count("my_key") == 1

        results = store.recall("updated")
        assert results
        assert results[0]["value"] == "updated"


class TestLearnCommand:
    def test_learn_command(self, store: MemoryStore) -> None:
        """learn() should parse input, save the fact, and return confirmation."""
        confirmation = store.learn("remember that the project uses port 8080")

        assert "Remembered:" in confirmation
        assert "port" in confirmation.lower() or "8080" in confirmation

        # Verify the value was actually persisted
        all_keys = store.list_keys()
        assert all_keys, "No keys found after learn()"

    def test_learn_colon_separator(self, store: MemoryStore) -> None:
        """learn() should split on colon when present."""
        confirmation = store.learn("database host: localhost")
        assert "localhost" in confirmation

        results = store.recall("localhost")
        assert results

    def test_learn_is_separator(self, store: MemoryStore) -> None:
        """learn() should split on ' is ' when present."""
        confirmation = store.learn("the API version is v2")
        assert "v2" in confirmation

    def test_learn_returns_string(self, store: MemoryStore) -> None:
        """learn() must always return a non-empty string."""
        result = store.learn("some random fact without clear structure")
        assert isinstance(result, str)
        assert len(result) > 0


class TestInitDb:
    def test_init_db_is_idempotent(self, tmp_path: Path) -> None:
        """Calling init_db() multiple times must not raise."""
        db_file = str(tmp_path / "idempotent.db")
        init_db(db_file)
        init_db(db_file)  # second call — should be a no-op
        init_db(db_file)  # third call

    def test_init_db_creates_directory(self, tmp_path: Path) -> None:
        """init_db() must create parent directories if they don't exist."""
        nested = tmp_path / "a" / "b" / "c" / "memory.db"
        init_db(str(nested))
        assert nested.exists()
