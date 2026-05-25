# ClawBro Architecture
**Version:** 1.0.0
**Date:** 2026-04-07
**Author:** Architect Agent (Claude claude-sonnet-4-6)
**Status:** Final — Ready for Implementation

---

## Design Plan (Pre-Write Outline)

Before writing each section, here is what this document covers and why each decision was made:

1. **System Overview** — Defines scope, non-goals, and the single-process constraint clearly so engineers don't over-engineer.
2. **Component Diagram** — ASCII art showing every major subsystem and data flow direction, including optional adapters.
3. **API Contracts** — Python class/method signatures with docstrings. This is the contract between modules — implementations must match these exactly.
4. **Tech Stack** — Pinned choices with rationale. No ambiguity about which library does what.
5. **Skill Router Design** — The routing algorithm in full, including scorer interface, confidence threshold, and fallback behavior.
6. **File Structure** — Exact layout with one-line description per file.
7. **Borrow vs. Build Table** — Clear lineage from ZeroClaw/OpenClaw decisions.
8. **Module Boundaries** — Each module's owns/does-not-own table. Prevents coupling creep.
9. **Data Flow Walkthrough** — Step-by-step trace of one user message through the full system.

---

## 1. System Overview

### What ClawBro Is

ClawBro is a personal AI assistant CLI built in Python 3.11+. It runs as a **single process** on the user's machine — no daemons, no WebSocket gateways, no background services. The user types a message; ClawBro routes it to the correct skill, runs the skill (calling Claude if needed), and returns a response to the terminal.

ClawBro is designed to run comfortably on:
- A Raspberry Pi 4 (4 GB RAM) or equivalent low-power ARM board.
- Any x86 laptop or desktop, Windows/macOS/Linux.
- Python 3.11+ (no compiled extensions required for core functionality).

### Goals

| Goal | Description |
|------|-------------|
| **Skill-first design** | Every non-trivial capability is a Skill — a self-describing, independently testable module. |
| **Minimal footprint** | Runs in <100 MB RAM at idle. No always-on daemon required. |
| **Claude as the brain** | The Anthropic Claude API is the default inference backend. Ollama is an optional offline fallback. |
| **SQLite as the only store** | All memory — short-term conversation history, long-term facts, skill state — lives in one SQLite file. |
| **Explicit autonomy** | Nothing happens automatically without user intent. No background scans, no auto-discovered skills, no agent swarms. |
| **Optional adapters** | Telegram and Discord adapters exist as optional entry points using the same Router/Skill core. |

### Non-Goals (Explicitly Out of Scope for v1.0)

- WebSocket gateway / control plane daemon
- Multi-user / multi-tenant operation
- Autonomous skill discovery (SkillForge-style)
- Agent swarms or parallel sub-agents
- Mobile companion apps
- Hardware GPIO / embedded targets
- Vector database / semantic memory (SQLite FTS5 is sufficient for v1.0)
- Multi-backend memory abstraction

### Core Constraints

1. **Single Python process.** No subprocess spawning for core logic (tools may spawn subprocesses).
2. **One SQLite file.** Located at `~/.clawbro/memory.db`. Created on first run.
3. **API key from environment.** `ANTHROPIC_API_KEY` via `.env` or shell export. Never hardcoded.
4. **Streaming responses.** Claude API is always called in streaming mode; output is printed token-by-token.
5. **Context window safety.** Conversation history is trimmed before each API call using head/tail truncation borrowed from ZeroClaw's `history.rs`.

---

## 2. Component Diagram

```
╔══════════════════════════════════════════════════════════════════╗
║                        ENTRY POINTS                             ║
║                                                                  ║
║  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────┐  ║
║  │   CLI Adapter   │  │ Telegram Adapter │  │ Discord Adapter│  ║
║  │  adapters/cli   │  │ adapters/telegram│  │ adapters/discord│ ║
║  │  (rich prompt)  │  │ (optional)       │  │ (optional)     │  ║
║  └────────┬────────┘  └────────┬─────────┘  └───────┬────────┘  ║
║           │                   │                     │           ║
╚═══════════╪═══════════════════╪═════════════════════╪═══════════╝
            │                   │                     │
            └───────────────────┼─────────────────────┘
                                │  InputMessage (text, source, user_id)
                                ▼
╔══════════════════════════════════════════════════════════════════╗
║                          CORE LAYER                             ║
║                                                                  ║
║  ┌──────────────────────────────────────────────────────────┐   ║
║  │                    SkillRouter                           │   ║
║  │                  core/router.py                          │   ║
║  │                                                          │   ║
║  │  1. Receive InputMessage                                 │   ║
║  │  2. Score all registered Skills (keyword + regex match)  │   ║
║  │  3. Pick highest-confidence Skill (threshold = 0.4)      │   ║
║  │  4. If no Skill clears threshold → FallbackSkill (Claude)│   ║
║  │  5. Call skill.handle(context) → SkillResult             │   ║
║  └──────────────────────────────────────────────────────────┘   ║
║           │                                 │                   ║
║           │ ConversationContext              │ SkillResult       ║
║           ▼                                 ▼                   ║
╚══════════════════════════════════════════════════════════════════╝
            │
            ├─────────────────────────────────────────────────┐
            ▼                                                 ▼
╔═══════════════════════════════╗   ╔══════════════════════════════╗
║         SKILLS LAYER          ║   ║        MEMORY LAYER          ║
║                               ║   ║                              ║
║  skills/base.py (SkillBase)   ║   ║  memory/store.py             ║
║  ┌───────────────────────┐    ║   ║  (MemoryStore facade)        ║
║  │ system_architect      │    ║   ║                              ║
║  │ knowledge_synthesizer │    ║   ║  ┌──────────────────────┐   ║
║  │ technical_proposal_   │    ║   ║  │  memory/short_term.py│   ║
║  │   generator           │    ║   ║  │  (ShortTermMemory)   │   ║
║  │ data_repurposer       │    ║   ║  │  In-memory ring buf  │   ║
║  │ sandbox_guard         │    ║   ║  │  + SQLite flush       │   ║
║  │ system_pulse          │    ║   ║  └──────────────────────┘   ║
║  │ research_summarizer   │    ║   ║                              ║
║  │ (FallbackSkill)       │    ║   ║  ┌──────────────────────┐   ║
║  └───────────────────────┘    ║   ║  │  memory/long_term.py │   ║
║                               ║   ║  │  (LongTermMemory)    │   ║
║  Each skill may call:         ║   ║  │  SQLite FTS5 search  │   ║
║  - ClaudeClient (streaming)   ║   ║  │  + structured facts  │   ║
║  - MemoryStore (read/write)   ║   ║  └──────────────────────┘   ║
╚═══════════════════════════════╝   ╚══════════════════════════════╝
            │
            ▼
╔══════════════════════════════════════════════════════════════════╗
║                      CLAUDE API CLIENT                          ║
║                    core/claude_client.py                        ║
║                                                                  ║
║  Wraps anthropic SDK.  Always streams.                          ║
║  Handles:                                                        ║
║    - Context truncation (head/tail algorithm)                   ║
║    - TurnEvent emission (Chunk, ToolCall, ToolResult, Done)     ║
║    - Ollama fallback (optional, same interface)                 ║
╚══════════════════════════════════════════════════════════════════╝
            │
            ▼
╔══════════════════════════════════════════════════════════════════╗
║                    EXTERNAL SERVICES                            ║
║                                                                  ║
║   ┌─────────────────────────┐   ┌────────────────────────────┐  ║
║   │   Anthropic Claude API  │   │  Ollama (local, optional)  │  ║
║   │   api.anthropic.com     │   │  localhost:11434           │  ║
║   └─────────────────────────┘   └────────────────────────────┘  ║
╚══════════════════════════════════════════════════════════════════╝
```

### Connection Legend

- **Solid arrows (→):** Synchronous Python calls within the same process.
- **TurnEvent stream:** An iterator/generator yielding `TurnEvent` objects from `ClaudeClient` to the calling Skill, which forwards chunks to the Adapter for real-time display.
- **SQLite:** All memory modules share one connection pool (thread-safe via `check_same_thread=False` + `WAL` mode).
- **Optional adapters:** Telegram and Discord adapters replace the CLI adapter as the entry point. The Router and everything below is unchanged.

---

## 3. API Contracts

These are the binding interfaces between modules. Implementations must match these signatures exactly. Where a method returns a generator, the generator protocol is specified.

### 3.1 `InputMessage` — Data class (core/context.py)

```python
@dataclass
class InputMessage:
    """
    A normalized message arriving from any adapter (CLI, Telegram, Discord).
    Adapters are responsible for constructing this object before passing to the Router.
    """
    text: str                      # Raw user text
    source: str                    # "cli" | "telegram" | "discord"
    user_id: str                   # Adapter-specific user identifier
    session_id: str                # UUID for this conversation session
    timestamp: float               # Unix epoch (time.time())
    metadata: dict                 # Adapter-specific extras (chat_id, message_id, etc.)
```

### 3.2 `ConversationContext` — Data class (core/context.py)

```python
@dataclass
class ConversationContext:
    """
    The full context object passed to every skill's handle() method.
    Skills read from this object and do NOT modify it directly —
    they interact with memory via MemoryStore methods.
    """
    message: InputMessage               # The triggering message
    history: list[dict]                 # List of {"role": str, "content": str} dicts
                                        # Already truncated to fit context window
    memory: "MemoryStore"               # Injected memory facade (read/write)
    claude: "ClaudeClient"              # Injected Claude client (call to stream)
    skill_name: str                     # Name of the skill that was selected
    confidence: float                   # Router confidence score that selected this skill
    session_id: str                     # Same as message.session_id
```

### 3.3 `TurnEvent` — Union type (core/context.py)

Borrowed directly from ZeroClaw's `TurnEvent` pattern, translated to Python dataclasses.

```python
from dataclasses import dataclass
from typing import Literal, Any

@dataclass
class ChunkEvent:
    """A streamed text token from the model."""
    kind: Literal["chunk"] = "chunk"
    text: str = ""

@dataclass
class ThinkingEvent:
    """Extended thinking token (Claude claude-sonnet-4-6+ models only)."""
    kind: Literal["thinking"] = "thinking"
    text: str = ""

@dataclass
class ToolCallEvent:
    """The model is requesting a tool call."""
    kind: Literal["tool_call"] = "tool_call"
    tool_name: str = ""
    tool_input: dict = None          # Parsed JSON input arguments
    tool_use_id: str = ""            # Anthropic tool_use block ID

@dataclass
class ToolResultEvent:
    """A tool has returned a result, about to be fed back to the model."""
    kind: Literal["tool_result"] = "tool_result"
    tool_use_id: str = ""
    result: Any = None
    is_error: bool = False

@dataclass
class DoneEvent:
    """The model turn is complete. Contains the full assembled text."""
    kind: Literal["done"] = "done"
    full_text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""            # "end_turn" | "tool_use" | "max_tokens"

# Union type alias used throughout the codebase
TurnEvent = ChunkEvent | ThinkingEvent | ToolCallEvent | ToolResultEvent | DoneEvent
```

### 3.4 `SkillResult` — Data class (skills/base.py)

```python
@dataclass
class SkillResult:
    """
    The structured result returned by any skill's handle() method.
    The adapter uses this to render output to the user.
    """
    text: str                          # Final assembled response text
    skill_name: str                    # Which skill produced this result
    success: bool = True               # False if the skill encountered an error
    error_message: str | None = None   # Human-readable error, if success=False
    metadata: dict = None              # Optional extra data (e.g., search results, file paths)
```

### 3.5 `SkillBase` — Abstract base class (skills/base.py)

```python
from abc import ABC, abstractmethod

class SkillBase(ABC):
    """
    Every skill must inherit from SkillBase and implement all abstract methods.
    Skills are instantiated once at startup and reused across turns.
    Skills must be stateless between calls — all state goes through MemoryStore.
    """

    # --- Class-level metadata (define on the class, not instance) ---

    name: str               # e.g. "system_architect"
    description: str        # One-sentence description shown in /help
    version: str            # Semver string e.g. "1.0.0"

    trigger_patterns: list[str]
    # List of regex patterns or keyword strings.
    # The router uses these to compute a confidence score.
    # Examples:
    #   ["architect", "design system", "draw.*diagram"]
    #   ["summarize", "tldr", "summary of"]

    # --- Required interface ---

    @abstractmethod
    def score(self, message: str) -> float:
        """
        Return a confidence score in [0.0, 1.0] indicating how well this skill
        matches the given raw message text.

        The router calls score() on every registered skill and picks the highest.
        The default implementation in SkillBase counts trigger_patterns matches —
        subclasses may override for more sophisticated scoring.

        Args:
            message: The raw user message text (lowercased before scoring).

        Returns:
            float in [0.0, 1.0]. 0.0 = definitely not this skill.
                                  1.0 = this skill is certain.
        """

    @abstractmethod
    def handle(self, context: ConversationContext) -> SkillResult:
        """
        Execute the skill's logic given the full conversation context.

        Skills should:
        1. Read context.history and context.message.text for inputs.
        2. Call context.claude.stream(...) or context.claude.complete(...) as needed.
        3. Optionally call context.memory.save() / context.memory.recall() for persistence.
        4. Return a SkillResult with the final assembled text.

        Skills must NOT:
        - Modify context directly.
        - Maintain instance-level state between calls.
        - Raise exceptions to the caller — catch internally and return SkillResult(success=False).

        Args:
            context: Full ConversationContext for this turn.

        Returns:
            SkillResult with assembled text and metadata.
        """
```

### 3.6 `SkillRouter` — Class (core/router.py)

```python
class SkillRouter:
    """
    Scores all registered skills against the incoming message and dispatches
    to the highest-confidence skill. Falls back to FallbackSkill if no skill
    clears the confidence threshold.
    """

    CONFIDENCE_THRESHOLD: float = 0.4
    # Skills scoring below this are not considered. Tune this if false-positives
    # or false-negatives become a problem in production use.

    def __init__(self, skills: list[SkillBase], fallback: SkillBase) -> None:
        """
        Args:
            skills: All registered skill instances, loaded at startup.
            fallback: The FallbackSkill (Claude general assistant). Used when
                      no registered skill clears the confidence threshold.
        """

    def register(self, skill: SkillBase) -> None:
        """
        Register a skill at runtime. Called during app startup for each skill.
        Raises ValueError if a skill with the same name is already registered.

        Args:
            skill: An instantiated SkillBase subclass.
        """

    def route(self, message: str) -> tuple[SkillBase, float]:
        """
        Score all registered skills and return the best match.

        Algorithm:
        1. Lowercase message.
        2. Call skill.score(message) for every registered skill.
        3. Sort by score descending.
        4. If top score >= CONFIDENCE_THRESHOLD, return (top_skill, top_score).
        5. Else return (self.fallback, 0.0).

        Args:
            message: Raw user message text.

        Returns:
            Tuple of (selected_skill, confidence_score).
        """

    def dispatch(self, message: InputMessage, context: ConversationContext) -> SkillResult:
        """
        Full pipeline: route the message, then call the skill's handle().

        Args:
            message: The normalized InputMessage from the adapter.
            context: The ConversationContext prepared by the adapter/session layer.

        Returns:
            SkillResult from the selected skill.
        """
```

### 3.7 `MemoryStore` — Facade (memory/store.py)

```python
class MemoryStore:
    """
    Unified facade over ShortTermMemory and LongTermMemory.
    Skills interact ONLY with MemoryStore — never with the underlying classes directly.
    Injected into ConversationContext at session start.
    """

    def __init__(self, session_id: str, db_path: str) -> None:
        """
        Args:
            session_id: UUID string for the current conversation session.
            db_path: Absolute path to the SQLite database file.
        """

    # --- Short-term (session-scoped) ---

    def add_turn(self, role: str, content: str) -> None:
        """
        Append one conversation turn to both the in-memory ring buffer
        and the SQLite conversation_turns table.

        Args:
            role: "user" | "assistant" | "tool"
            content: Text content of the turn.
        """

    def get_history(self, max_tokens: int = 8000) -> list[dict]:
        """
        Return conversation history as a list of {"role": str, "content": str} dicts,
        trimmed using head/tail truncation to fit within max_tokens.

        Truncation algorithm (borrowed from ZeroClaw history.rs):
        1. Estimate tokens as len(content) // 4 (fast approximation).
        2. Always keep the first 2 turns (system context).
        3. Always keep the last 6 turns (recent context).
        4. Trim from the middle if over budget, inserting a
           "[...N turns truncated...]" placeholder.

        Args:
            max_tokens: Token budget for history. Default matches Claude's practical limit
                        for context after system prompt overhead.

        Returns:
            List of message dicts ready to pass to the Anthropic SDK.
        """

    def clear_session(self) -> None:
        """
        Clear the in-memory ring buffer for this session.
        SQLite rows are retained (for audit/recall purposes).
        """

    # --- Long-term (persistent, cross-session) ---

    def save(self, key: str, value: str, metadata: dict | None = None) -> None:
        """
        Persist a named fact to the long-term SQLite store.
        If a record with the same key already exists, it is overwritten.

        Args:
            key: Unique identifier for the fact (e.g., "user_preference_theme").
            value: String value to store (may be JSON-serialized for structured data).
            metadata: Optional dict with extra fields (tags, source, etc.).
                      Stored as JSON in the metadata column.
        """

    def recall(self, query: str, limit: int = 5) -> list[dict]:
        """
        Full-text search over the long-term store using SQLite FTS5.

        Args:
            query: Search query string. Supports FTS5 operators (AND, OR, NOT, NEAR).
            limit: Maximum number of results to return.

        Returns:
            List of dicts, each with keys: key, value, metadata, created_at, updated_at.
            Ordered by FTS5 relevance score descending.
        """

    def delete(self, key: str) -> bool:
        """
        Delete a long-term memory record by key.

        Args:
            key: The key to delete.

        Returns:
            True if a record was deleted, False if the key did not exist.
        """

    def list_keys(self, prefix: str = "") -> list[str]:
        """
        List all long-term memory keys, optionally filtered by prefix.

        Args:
            prefix: If non-empty, only keys starting with this prefix are returned.

        Returns:
            List of key strings, ordered alphabetically.
        """
```

### 3.8 `ClaudeClient` — Class (core/claude_client.py)

```python
import anthropic
from typing import Iterator

class ClaudeClient:
    """
    Wraps the Anthropic Python SDK.
    Always uses streaming. Handles context truncation before each call.
    Emits TurnEvent objects through a generator interface.

    Skills call this class; they never import `anthropic` directly.
    """

    DEFAULT_MODEL: str = "claude-sonnet-4-6"
    MAX_TOKENS: int = 8096
    HISTORY_TOKEN_BUDGET: int = 8000   # Passed to MemoryStore.get_history()

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        """
        Args:
            api_key: Anthropic API key. Sourced from ANTHROPIC_API_KEY env var.
            model: Claude model ID. Can be overridden per-call.
        """

    def stream(
        self,
        system_prompt: str,
        history: list[dict],
        user_message: str,
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> Iterator[TurnEvent]:
        """
        Stream a Claude API call, yielding TurnEvent objects.

        Behavior:
        - Opens a streaming message with the Anthropic SDK.
        - Yields ChunkEvent for each text delta.
        - Yields ThinkingEvent for thinking block deltas (if model supports it).
        - Yields ToolCallEvent when the model requests a tool.
        - Yields ToolResultEvent after the caller handles the tool and feeds back.
        - Yields DoneEvent with full assembled text and token counts when done.
        - If the model returns stop_reason="tool_use", the generator pauses at
          ToolCallEvent and waits for the caller to send tool results before continuing.
          (Implemented via a two-phase generator or callback pattern.)

        Args:
            system_prompt: The system prompt string for this turn.
            history: List of message dicts (already token-trimmed by MemoryStore).
            user_message: The current user turn text.
            tools: Optional list of Anthropic tool spec dicts.
            model: Override model for this call only.

        Yields:
            TurnEvent subclass instances in emission order.
        """

    def complete(
        self,
        system_prompt: str,
        history: list[dict],
        user_message: str,
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> str:
        """
        Convenience wrapper: drains stream() and returns the full assembled text.
        Use this when the skill does not need token-by-token streaming.

        Args: Same as stream().

        Returns:
            Fully assembled response text string.
        """

    def _truncate_tool_result(self, result: str, max_chars: int = 4000) -> str:
        """
        Truncate a tool result string using head-2/3 + tail-1/3 with ellipsis.
        Borrowed from ZeroClaw's truncate_tool_result() in history.rs.

        This prevents a single large tool result from dominating the context window.

        Args:
            result: Raw tool result string.
            max_chars: Maximum character length after truncation. Default 4000.

        Returns:
            Truncated string with "[...truncated...]" marker in the middle if needed.
        """
```

### 3.9 `ShortTermMemory` — Class (memory/short_term.py)

```python
from collections import deque

class ShortTermMemory:
    """
    In-memory ring buffer for the current conversation session's turns.
    Also persists each turn to SQLite for durability and recall.

    Used internally by MemoryStore. Not accessed directly by skills.
    """

    MAX_TURNS: int = 50
    # Ring buffer capacity. Oldest turns are dropped when exceeded.
    # SQLite rows are never dropped — only the in-memory buffer rotates.

    def __init__(self, session_id: str, db_connection: "sqlite3.Connection") -> None:
        """
        Args:
            session_id: UUID for this session. All SQLite rows are tagged with this.
            db_connection: Shared SQLite connection. ShortTermMemory does NOT open
                           its own connection.
        """

    def add(self, role: str, content: str) -> None:
        """Append a turn to the ring buffer and flush to SQLite."""

    def get_all(self) -> list[dict]:
        """Return all turns from the in-memory buffer as message dicts."""

    def clear(self) -> None:
        """Clear the in-memory buffer. Does NOT delete SQLite rows."""
```

### 3.10 `LongTermMemory` — Class (memory/long_term.py)

```python
class LongTermMemory:
    """
    Persistent key-value store backed by SQLite with FTS5 full-text search.
    Stores named facts, preferences, and cross-session knowledge.

    Used internally by MemoryStore. Not accessed directly by skills.

    SQLite Schema:
        CREATE VIRTUAL TABLE long_term_fts USING fts5(key, value, content=long_term);
        CREATE TABLE long_term (
            key       TEXT PRIMARY KEY,
            value     TEXT NOT NULL,
            metadata  TEXT,           -- JSON blob
            created_at REAL NOT NULL, -- Unix epoch
            updated_at REAL NOT NULL
        );
    """

    def __init__(self, db_connection: "sqlite3.Connection") -> None:
        """
        Args:
            db_connection: Shared SQLite connection.
        """

    def upsert(self, key: str, value: str, metadata: dict | None) -> None:
        """Insert or update a record. Triggers FTS5 index update."""

    def search(self, query: str, limit: int) -> list[dict]:
        """FTS5 search. Returns ranked results."""

    def get(self, key: str) -> dict | None:
        """Exact key lookup. Returns None if not found."""

    def delete(self, key: str) -> bool:
        """Delete by key. Returns True if deleted."""

    def list_keys(self, prefix: str) -> list[str]:
        """Return all keys with optional prefix filter."""
```

---

## 4. Tech Stack

| Layer | Library | Version | Rationale |
|-------|---------|---------|-----------|
| **Language** | Python | 3.11+ | Dataclasses, `match` statements, `tomllib` stdlib, speed improvements |
| **Claude API** | `anthropic` | ^0.50.0 | Official Anthropic SDK, streaming support, tool use |
| **CLI formatting** | `rich` | ^13.0 | Pretty tables, syntax highlighting, streaming output panels |
| **Env config** | `python-dotenv` | ^1.0 | Load `.env` file into `os.environ` on startup |
| **Memory** | `sqlite3` | stdlib | No extra dependency. WAL mode, FTS5 extension |
| **Telegram adapter** | `python-telegram-bot` | ^21.0 | Optional. Async-first, well-maintained |
| **Discord adapter** | `discord.py` | ^2.3 | Optional. Async-first, slash commands support |
| **Local LLM fallback** | `ollama` (HTTP) | n/a | Optional. Call via `httpx` to `localhost:11434` — no SDK needed |
| **Testing** | `pytest` | ^8.0 | Standard. `pytest-asyncio` for async adapter tests |
| **HTTP client** | `httpx` | ^0.27 | Used only for Ollama fallback. `anthropic` SDK handles its own HTTP |
| **Config file** | `tomllib` | stdlib (3.11+) | Parse `~/.clawbro/config.toml`. No extra dependency |
| **Type checking** | `mypy` | ^1.10 | Strict mode on `core/` and `memory/`. Skills are checked but may use `# type: ignore` sparingly |
| **Linting** | `ruff` | ^0.5 | Fast, single tool replaces flake8 + isort + pyupgrade |

### Configuration File (TOML)

ClawBro reads `~/.clawbro/config.toml` on startup. If not found, uses defaults.

```toml
# ~/.clawbro/config.toml

[claude]
model = "claude-sonnet-4-6"
max_tokens = 8096
history_token_budget = 8000

[memory]
db_path = "~/.clawbro/memory.db"
short_term_max_turns = 50

[router]
confidence_threshold = 0.4

[adapters.telegram]
enabled = false
# token = set via TELEGRAM_BOT_TOKEN env var

[adapters.discord]
enabled = false
# token = set via DISCORD_BOT_TOKEN env var

[ollama]
enabled = false
base_url = "http://localhost:11434"
model = "llama3.2"
```

---

## 5. Skill Router Design

### Overview

The router is a simple, deterministic confidence scorer. It does NOT call the LLM to decide routing — that would be slow and expensive. Instead, each skill exposes a `score()` method that computes a confidence float based on the raw message text.

### Scoring Algorithm

```
CONFIDENCE_THRESHOLD = 0.4

def route(message: str) -> tuple[SkillBase, float]:
    lowered = message.lower().strip()
    scores = [(skill, skill.score(lowered)) for skill in registered_skills]
    scores.sort(key=lambda x: x[1], reverse=True)

    best_skill, best_score = scores[0]
    if best_score >= CONFIDENCE_THRESHOLD:
        return (best_skill, best_score)
    else:
        return (fallback_skill, 0.0)
```

### Default `SkillBase.score()` Implementation

The base class provides a default implementation that skills can use or override:

```python
def score(self, message: str) -> float:
    """
    Default implementation: keyword/regex match counter.

    Algorithm:
    1. For each pattern in self.trigger_patterns:
       - If pattern is a plain string: check if it's a substring of message.
       - If pattern starts with '^' or contains regex metacharacters: compile and search.
    2. Count matches.
    3. Normalize: score = min(1.0, matches / len(trigger_patterns))
       (at least one match needed for non-zero score)
    4. Boost: if any single pattern matches AND the match is at the start of the
       message, add 0.1 to the score (capped at 1.0).
    """
```

### Skill Registration (at startup in main.py)

```python
router = SkillRouter(skills=[], fallback=FallbackSkill())

router.register(SystemArchitectSkill())
router.register(KnowledgeSynthesizerSkill())
router.register(TechnicalProposalGeneratorSkill())
router.register(DataRepurposerSkill())
router.register(SandboxGuardSkill())
router.register(SystemPulseSkill())
router.register(ResearchSummarizerSkill())
```

### Trigger Pattern Examples per Skill

| Skill | trigger_patterns |
|-------|-----------------|
| `SystemArchitectSkill` | `["architect", "design system", "draw diagram", "component diagram", "system design", "architecture"]` |
| `KnowledgeSynthesizerSkill` | `["synthesize", "combine", "knowledge", "connect.*ideas", "link.*concepts"]` |
| `TechnicalProposalGeneratorSkill` | `["proposal", "technical spec", "write.*spec", "rfc", "technical document"]` |
| `DataRepurposerSkill` | `["repurpose", "reformat", "convert.*data", "transform.*data", "restructure"]` |
| `SandboxGuardSkill` | `["sandbox", "safe.*run", "isolate", "execute.*safely", "check.*security"]` |
| `SystemPulseSkill` | `["system.*status", "pulse", "health.*check", "disk.*usage", "cpu.*usage", "memory.*usage"]` |
| `ResearchSummarizerSkill` | `["summarize", "summary", "tldr", "research", "paper", "article.*summary"]` |
| `FallbackSkill` | `[]` — never scores; only used when all others score below threshold |

### Fallback Behavior

`FallbackSkill` wraps a plain Claude API call with no special system prompt additions. It is the general-purpose assistant. When it handles a turn, `SkillResult.skill_name = "fallback"` and `SkillResult.metadata = {"confidence": 0.0}`.

---

## 6. File Structure

```
claudeclaw/
├── outputs/
│   └── src/                              # ClawBro source root
│       ├── main.py                       # Entry point: parse args, init all components, run adapter
│       │
│       ├── core/
│       │   ├── __init__.py               # Re-exports: SkillRouter, ConversationContext, ClaudeClient
│       │   ├── router.py                 # SkillRouter class — dispatch logic, confidence scoring
│       │   ├── context.py                # InputMessage, ConversationContext, TurnEvent dataclasses
│       │   └── claude_client.py          # ClaudeClient — streaming wrapper, tool loop, truncation
│       │
│       ├── skills/
│       │   ├── __init__.py               # Re-exports all skill classes + SkillBase
│       │   ├── base.py                   # SkillBase ABC + SkillResult dataclass
│       │   ├── system_architect.py       # Skill: system design diagrams and architecture docs
│       │   ├── knowledge_synthesizer.py  # Skill: cross-domain knowledge linking and synthesis
│       │   ├── technical_proposal_generator.py  # Skill: RFC / technical spec writing
│       │   ├── data_repurposer.py        # Skill: data format conversion and restructuring
│       │   ├── sandbox_guard.py          # Skill: safe code execution analysis and sandboxing advice
│       │   ├── system_pulse.py           # Skill: system health metrics (disk, CPU, RAM via psutil)
│       │   └── research_summarizer.py    # Skill: article/paper summarization and extraction
│       │
│       ├── memory/
│       │   ├── __init__.py               # Re-exports: MemoryStore
│       │   ├── short_term.py             # ShortTermMemory — ring buffer + SQLite flush
│       │   ├── long_term.py              # LongTermMemory — FTS5 key-value store
│       │   └── store.py                  # MemoryStore facade — unified API for skills
│       │
│       └── adapters/
│           ├── __init__.py               # Re-exports adapter classes
│           ├── cli.py                    # CLIAdapter — rich prompt, streaming output renderer
│           ├── telegram_adapter.py       # TelegramAdapter — python-telegram-bot integration
│           └── discord_adapter.py        # DiscordAdapter — discord.py integration
│
├── setup.sh                              # Bootstrap: venv create, pip install, .env copy
├── .env.example                          # Template: ANTHROPIC_API_KEY=, TELEGRAM_BOT_TOKEN=, etc.
├── requirements.txt                      # Pinned deps for core + optional adapters
└── README.md                             # User-facing: quickstart, config, skill list
```

### File Responsibilities (one line each)

| File | Owns |
|------|------|
| `main.py` | CLI argument parsing (`argparse`), component wiring, adapter selection, startup logging |
| `core/router.py` | Skill registry, confidence scoring loop, dispatch |
| `core/context.py` | All shared data structures (no logic, only dataclasses) |
| `core/claude_client.py` | Anthropic SDK calls, streaming, tool result truncation, Ollama fallback |
| `skills/base.py` | `SkillBase` ABC, `SkillResult` dataclass, default `score()` implementation |
| `skills/system_architect.py` | ASCII/mermaid diagram generation, architecture document drafting |
| `skills/knowledge_synthesizer.py` | Multi-document synthesis, concept linking |
| `skills/technical_proposal_generator.py` | RFC/spec generation, template filling |
| `skills/data_repurposer.py` | CSV↔JSON↔YAML conversion, data schema transformation |
| `skills/sandbox_guard.py` | Code safety analysis, subprocess sandboxing recommendations |
| `skills/system_pulse.py` | `psutil` stats collection, formatted health report |
| `skills/research_summarizer.py` | Paper/article reading and structured summarization |
| `memory/short_term.py` | In-memory ring buffer, per-session SQLite writes |
| `memory/long_term.py` | SQLite FTS5 CRUD, key-value persistence |
| `memory/store.py` | Unified facade; session-scoped `MemoryStore` instances |
| `adapters/cli.py` | `rich` Live panel rendering, streaming token output, REPL loop |
| `adapters/telegram_adapter.py` | Telegram bot handler, message normalization to `InputMessage` |
| `adapters/discord_adapter.py` | Discord slash command handler, message normalization |

---

## 7. What We're Borrowing vs. Building Custom

| Feature | Source | Decision | Notes |
|---------|--------|----------|-------|
| `TurnEvent` streaming pattern | ZeroClaw `agent.rs` | **Borrow** (translated to Python) | Typed event stream decouples rendering from inference |
| Trait-driven interfaces | ZeroClaw | **Borrow concept** (Python ABCs instead of Rust traits) | `SkillBase`, `MemoryStore`, adapters all use ABC pattern |
| Context compression (LLM summarization of middle history) | ZeroClaw `context_compressor.rs` | **Defer to v1.1** | Head/tail truncation is sufficient for v1.0; LLM summarization adds API cost |
| Head/tail history truncation | ZeroClaw `history.rs` | **Borrow** (reimplement in Python) | Same algorithm: keep first N + last N, trim middle |
| Tool result truncation (head 2/3 + tail 1/3) | ZeroClaw `history.rs` | **Borrow** (reimplement in Python) | Prevents large tool output from blowing context |
| SKILL.md structured descriptors | OpenClaw + ZeroClaw | **Borrow concept** (Python class metadata instead of markdown files) | Skills are Python classes with class-level metadata. SKILL.md loading is a v1.1 feature |
| SQLite as memory backend | ZeroClaw | **Borrow** (simplified — no multi-backend trait) | One backend, zero abstraction overhead |
| FTS5 full-text search | ZeroClaw `memory/mod.rs` | **Borrow** (same SQLite FTS5 approach) | Proven, no extra deps |
| WebSocket gateway / control plane | OpenClaw + ZeroClaw | **Skip** | Single process is simpler and sufficient |
| SkillForge auto-discovery | ZeroClaw `skillforge/` | **Skip** | Explicit autonomy is a core design principle |
| Agent swarms / Hands | ZeroClaw `hands/` | **Skip** | No autonomous background agents |
| SOP engine (YAML workflow triggers) | ZeroClaw `sop/` | **Skip** | Overkill for v1.0; revisit if automation use cases emerge |
| Multi-backend memory abstraction | ZeroClaw `Memory` trait | **Skip** | One backend (SQLite) until a real need arises |
| Personality system (SOUL.md, IDENTITY.md) | ZeroClaw `personality.rs` | **Simplify** | Single system prompt in `claude_client.py`; user can edit it |
| Thinking level control | ZeroClaw `thinking.rs` | **Simplify** | Expose `--thinking` CLI flag mapped to `budget_tokens` in the API call |
| Pairing guard / access control | ZeroClaw `security/` | **Simplify** | CLI is local-only. Telegram/Discord adapters use bot token auth only |
| Plugin / npm extension system | OpenClaw | **Skip** | Python package imports are sufficient; no runtime plugin loading |
| Ollama fallback | Neither (custom) | **Build** | Simple `httpx` POST to `localhost:11434/api/chat`; same `ClaudeClient` interface |

---

## 8. Module Boundaries

Each module has a strict owns/does-not-own table. Coupling violations must be caught in code review.

### `core/context.py`
| Owns | Does NOT Own |
|------|-------------|
| All shared dataclasses (`InputMessage`, `ConversationContext`, `TurnEvent*`, etc.) | Any business logic |
| Type aliases | Database access |
| No imports from other ClawBro modules | Claude API calls |

### `core/router.py`
| Owns | Does NOT Own |
|------|-------------|
| Skill registry (`list[SkillBase]`) | Skill implementations |
| Confidence scoring loop | Memory access |
| Dispatch to skill | Claude API calls |
| Fallback selection | Adapter-specific rendering |

### `core/claude_client.py`
| Owns | Does NOT Own |
|------|-------------|
| `anthropic` SDK import and usage | Memory access |
| Streaming and `TurnEvent` emission | Skill selection |
| Tool result truncation | Conversation history management |
| Ollama fallback HTTP call | System prompt content (passed in by callers) |

### `skills/*.py` (each skill)
| Owns | Does NOT Own |
|------|-------------|
| Skill-specific prompt construction | Other skills' logic |
| Calling `context.claude.stream()` or `.complete()` | Routing decisions |
| Calling `context.memory.save()` / `.recall()` | Importing `anthropic` directly |
| Returning `SkillResult` | Importing `sqlite3` directly |
| `trigger_patterns` and `score()` logic | Rendering output (return text only) |

### `memory/store.py`
| Owns | Does NOT Own |
|------|-------------|
| Creating `ShortTermMemory` and `LongTermMemory` instances | Claude API calls |
| Exposing unified `MemoryStore` API to skills | Routing decisions |
| Session scoping | Skill implementations |

### `memory/short_term.py`
| Owns | Does NOT Own |
|------|-------------|
| In-memory ring buffer (`deque`) | Long-term persistence |
| Per-turn SQLite inserts to `conversation_turns` table | FTS5 search |
| `get_history()` with truncation | Business logic |

### `memory/long_term.py`
| Owns | Does NOT Own |
|------|-------------|
| SQLite `long_term` table CRUD | Conversation history |
| FTS5 index management | Session management |
| Key-value upsert/search/delete | Any Claude calls |

### `adapters/cli.py`
| Owns | Does NOT Own |
|------|-------------|
| REPL loop (`while True: input()`) | Routing |
| `rich` Live panel for streaming output | Skill implementations |
| `InputMessage` construction from raw terminal input | Memory |
| Rendering `SkillResult` to terminal | Claude API |

### `adapters/telegram_adapter.py` / `adapters/discord_adapter.py`
| Owns | Does NOT Own |
|------|-------------|
| Bot framework setup and event handlers | Routing (delegates to Router) |
| Normalizing platform messages to `InputMessage` | Skill implementations |
| Sending `SkillResult.text` back to the platform | Memory |
| Bot token loading from env | Claude API |

---

## 9. Data Flow Walkthrough

**Scenario:** User types `"Design me a system architecture for a URL shortener"` at the CLI prompt.

---

**Step 1 — Adapter receives input**

`adapters/cli.py` reads the input string from the terminal via `rich`'s `Prompt.ask()`.

It constructs:
```python
InputMessage(
    text="Design me a system architecture for a URL shortener",
    source="cli",
    user_id="local",
    session_id="a1b2c3d4-...",   # UUID generated at session start
    timestamp=1744000000.0,
    metadata={}
)
```

---

**Step 2 — Router scores all skills**

`core/router.py` receives the `InputMessage`. It lowercases the text:
`"design me a system architecture for a url shortener"`

It calls `skill.score(lowered)` for every registered skill:

| Skill | Pattern Hit | Score |
|-------|------------|-------|
| `SystemArchitectSkill` | "architecture", "system" → 2/6 + start boost = **0.43** | 0.43 |
| `KnowledgeSynthesizerSkill` | no hit | 0.0 |
| `TechnicalProposalGeneratorSkill` | no hit | 0.0 |
| `DataRepurposerSkill` | no hit | 0.0 |
| `SandboxGuardSkill` | no hit | 0.0 |
| `SystemPulseSkill` | "system" alone → 1/6 = **0.16** | 0.16 |
| `ResearchSummarizerSkill` | no hit | 0.0 |

`SystemArchitectSkill` wins with 0.43 ≥ threshold 0.4.

Router returns `(SystemArchitectSkill, 0.43)`.

---

**Step 3 — Context is prepared**

The adapter (or `main.py` session layer) constructs a `ConversationContext`:

```python
# Retrieve trimmed history from MemoryStore
history = memory_store.get_history(max_tokens=8000)
# Returns e.g. last 3 turns from earlier in the session

context = ConversationContext(
    message=input_message,
    history=history,
    memory=memory_store,
    claude=claude_client,
    skill_name="system_architect",
    confidence=0.43,
    session_id="a1b2c3d4-..."
)
```

---

**Step 4 — Skill handles the request**

`SystemArchitectSkill.handle(context)` is called. Inside:

1. Builds a skill-specific system prompt:
   ```
   "You are an expert software architect. When asked to design a system,
    produce an ASCII component diagram followed by a description of each component..."
   ```

2. Calls `context.claude.stream(system_prompt, history, context.message.text)`.

3. Iterates over the returned `TurnEvent` generator:
   - For each `ChunkEvent`: appends token to a `response_buffer` string AND yields the chunk upstream to the adapter for live rendering.
   - For each `ToolCallEvent`: executes the tool (e.g., `memory_recall`), feeds `ToolResultEvent` back.
   - For `DoneEvent`: breaks the loop.

4. Calls `context.memory.add_turn("user", context.message.text)`.
5. Calls `context.memory.add_turn("assistant", response_buffer)`.
6. Optionally calls `context.memory.save("last_architecture_request", context.message.text)` for long-term recall.

7. Returns:
   ```python
   SkillResult(
       text=response_buffer,
       skill_name="system_architect",
       success=True,
       metadata={"confidence": 0.43}
   )
   ```

---

**Step 5 — Claude API streaming**

Inside `ClaudeClient.stream()`:

1. Calls `anthropic.Anthropic().messages.stream(...)` with:
   - `model="claude-sonnet-4-6"`
   - `system=system_prompt`
   - `messages=[...history..., {"role": "user", "content": "Design me..."}]`
   - `max_tokens=8096`

2. For each event from the SDK stream:
   - `text_delta` → `yield ChunkEvent(text=delta.text)`
   - `content_block_stop` with thinking → `yield ThinkingEvent(text=block.thinking)`
   - `tool_use` block → `yield ToolCallEvent(tool_name=..., tool_input=..., tool_use_id=...)`
   - Stream end → `yield DoneEvent(full_text=assembled, input_tokens=..., output_tokens=...)`

---

**Step 6 — Adapter renders streaming output**

`adapters/cli.py` maintains a `rich.Live` panel. As `ChunkEvent` objects arrive (forwarded by the skill), it appends each token to the panel's markdown content and refreshes the display — giving the user a live token-by-token output experience.

When `SkillResult` is returned, the adapter prints a dim status line:
```
[system_architect | confidence: 0.43 | 512 tokens]
```

---

**Step 7 — Memory persists the turn**

`MemoryStore.add_turn()` was called twice in Step 4. This:
1. Appends both turns to the in-memory `deque`.
2. Inserts two rows into the `conversation_turns` SQLite table:
   ```sql
   INSERT INTO conversation_turns (session_id, role, content, created_at)
   VALUES ('a1b2c3d4-...', 'user', 'Design me...', 1744000000.0);

   INSERT INTO conversation_turns (session_id, role, content, created_at)
   VALUES ('a1b2c3d4-...', 'assistant', '## URL Shortener Architecture\n\n...', 1744000010.0);
   ```

The next user turn will retrieve these rows via `get_history()`, and Claude will have full context of the prior exchange.

---

**Full sequence summary:**

```
CLI input
  → InputMessage construction          [adapters/cli.py]
    → SkillRouter.route()              [core/router.py]
      → skill.score() × N             [skills/*.py]
    → SkillRouter.dispatch()           [core/router.py]
      → ConversationContext built      [main.py / session layer]
        → MemoryStore.get_history()    [memory/store.py → short_term.py]
      → SystemArchitectSkill.handle()  [skills/system_architect.py]
        → ClaudeClient.stream()        [core/claude_client.py]
          → anthropic SDK (streaming)  [external]
          → yield TurnEvent*           [core/context.py]
        → MemoryStore.add_turn() × 2  [memory/store.py → short_term.py]
        → return SkillResult           [skills/base.py]
    → CLIAdapter renders SkillResult   [adapters/cli.py]
```

---

## Appendix A: SQLite Schema

```sql
-- Conversation history (short-term, session-scoped)
CREATE TABLE IF NOT EXISTS conversation_turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    role        TEXT    NOT NULL CHECK(role IN ('user', 'assistant', 'tool')),
    content     TEXT    NOT NULL,
    created_at  REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON conversation_turns(session_id, created_at);

-- Long-term fact store
CREATE TABLE IF NOT EXISTS long_term (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    metadata    TEXT,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

-- FTS5 index on long_term
CREATE VIRTUAL TABLE IF NOT EXISTS long_term_fts
    USING fts5(key, value, content=long_term, content_rowid=rowid);

-- Triggers to keep FTS5 in sync
CREATE TRIGGER IF NOT EXISTS long_term_ai
    AFTER INSERT ON long_term BEGIN
        INSERT INTO long_term_fts(rowid, key, value) VALUES (new.rowid, new.key, new.value);
    END;

CREATE TRIGGER IF NOT EXISTS long_term_ad
    AFTER DELETE ON long_term BEGIN
        INSERT INTO long_term_fts(long_term_fts, rowid, key, value)
            VALUES ('delete', old.rowid, old.key, old.value);
    END;

CREATE TRIGGER IF NOT EXISTS long_term_au
    AFTER UPDATE ON long_term BEGIN
        INSERT INTO long_term_fts(long_term_fts, rowid, key, value)
            VALUES ('delete', old.rowid, old.key, old.value);
        INSERT INTO long_term_fts(rowid, key, value) VALUES (new.rowid, new.key, new.value);
    END;
```

---

## Appendix B: Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API key |
| `CLAWBRO_MODEL` | No | `claude-sonnet-4-6` | Override default Claude model |
| `CLAWBRO_DB_PATH` | No | `~/.clawbro/memory.db` | Override SQLite database path |
| `CLAWBRO_CONFIG_PATH` | No | `~/.clawbro/config.toml` | Override config file path |
| `TELEGRAM_BOT_TOKEN` | No | — | Required if Telegram adapter is enabled |
| `DISCORD_BOT_TOKEN` | No | — | Required if Discord adapter is enabled |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434` | Override Ollama endpoint |

---

## Appendix C: `requirements.txt` (Pinned)

```
# Core (always required)
anthropic>=0.50.0
rich>=13.7.0
python-dotenv>=1.0.0
httpx>=0.27.0        # Ollama fallback HTTP client

# Optional: adapters
python-telegram-bot>=21.0.0
discord.py>=2.3.0

# Dev / Testing
pytest>=8.0.0
pytest-asyncio>=0.23.0
mypy>=1.10.0
ruff>=0.5.0
```

Core deps total: 4 packages + their transitive deps. Expected venv size: ~40 MB. Within budget for Raspberry Pi.

---

*This document is the binding architecture specification for ClawBro v1.0. All implementation decisions in `outputs/src/` must trace back to a section in this document. Deviations require a documented rationale and an update to the relevant section.*
