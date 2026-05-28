# ClawBro Architecture
**Version:** 1.0.0
**Date:** 2026-04-07 (reconciled with the implementation 2026-05-25)
**Author:** Architect Agent (Claude claude-sonnet-4-6)
**Status:** Implemented — this document has been updated to match the code in `src/`.

> **Reconciliation note (2026-05-25):** the original spec was written before
> implementation. It has since been edited to reflect what was actually built —
> notably: env-var configuration (no TOML/`tomllib`); `requests` for the Ollama
> fallback (not `httpx`); skills calling `complete()` with the system prompt as a
> leading user message; the adapter (not the skill) handling memory writes; the
> `--adapter {cli,telegram,discord}` entry-point flag; the `file_writer` skill;
> and the actual SQLite schema (`long_term_memory`, `timestamp` column). Where a
> detail might still drift (e.g. per-skill `trigger_patterns`), the source under
> `src/` is authoritative.

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
║  │ file_writer           │    ║   ║  ┌──────────────────────┐   ║
║  │ (FallbackSkill)       │    ║   ║  │  memory/long_term.py │   ║
║  └───────────────────────┘    ║   ║  │  (LongTermMemory)    │   ║
║                               ║   ║  │  SQLite FTS5 search  │   ║
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
        The default implementation in SkillBase counts how many trigger_patterns
        match, then divides by a fixed denominator of 3 (capped at 1.0) — so two
        pattern hits clear the 0.4 threshold and three saturate to 1.0. Subclasses
        may override for more sophisticated scoring.

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
        Register a skill. Called during app startup for each skill.
        Raises TypeError if the argument is not a SkillBase instance.
        (Duplicate names are not rejected — registration is append-only.)

        Args:
            skill: An instantiated SkillBase subclass.
        """

    def route(self, message: str) -> tuple[SkillBase, float]:
        """
        Score all registered skills and return the best match.

        Algorithm:
        1. Call skill.score(message) for every registered skill, tracking the
           highest score seen (a skill raising in score() is treated as 0.0).
        2. If the best score >= CONFIDENCE_THRESHOLD, return (best_skill, best_score).
        3. Else return (self.fallback, 0.0).

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

    def __init__(self, session_id: str, db_path: str | None = None) -> None:
        """
        Args:
            session_id: UUID string for the current conversation session.
            db_path: Path to the SQLite database file. If None, defaults to
                     ~/.clawbro/memory.db. The connection is opened with
                     check_same_thread=False, WAL mode, and foreign keys on.
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
        Clear this session's conversation history — both the in-memory ring
        buffer and the SQLite rows for this session_id.
        """

    def learn(self, text: str) -> str:
        """
        Convenience helper: parse a natural-language statement into a
        (key, value) pair using simple heuristics (strips preambles like
        "remember that", splits on ':', ' is ', ' = ', etc.) and saves it to
        long-term memory. Returns a confirmation string. No Claude call.
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

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        use_ollama: bool = False,
        ollama_model: str = "llama3",
        ollama_host: str = "http://localhost:11434",
        ollama_api_key: str = "",
    ) -> None:
        """
        Args:
            api_key: Anthropic API key. Sourced from ANTHROPIC_API_KEY env var.
            model: Claude model ID. Can be overridden per-call.
            use_ollama: Route calls to Ollama instead of the Claude API.
            ollama_model / ollama_host / ollama_api_key: Ollama configuration.
                When an API key is present, calls hit ollama.com directly; with
                no key, calls hit the local host. On a 401/403 the client falls
                back transparently to the Claude API.
        """

    def stream(
        self,
        messages: list[dict],
        system: str = "",
        max_tokens: int = 2048,
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> Iterator[TurnEvent]:
        """
        Stream a Claude (or Ollama) call, yielding TurnEvent objects.

        Behavior:
        - Opens a streaming message with the Anthropic SDK.
        - Yields ChunkEvent for each text delta.
        - Yields ThinkingEvent for thinking block deltas (if the model emits them).
        - Yields ToolCallEvent when the model requests a tool.
        - Yields DoneEvent with the full assembled text and token counts at the end.
        - If use_ollama is set, streams from Ollama instead; an Ollama 401/403
          falls back to the Claude API mid-stream.

        Note: the full message list (history + current user turn) is passed in as
        `messages` by the caller; the system prompt is a separate `system` arg.

        Args:
            messages: Conversation history including the current user message.
            system: System prompt string (default "").
            max_tokens: Max tokens to generate (default 2048).
            tools: Optional list of Anthropic tool spec dicts.
            model: Override model for this call only.

        Yields:
            TurnEvent subclass instances in emission order.
        """

    def complete(
        self,
        messages: list[dict],
        system: str = "",
        max_tokens: int = 2048,
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

This table reflects the libraries actually used in the current build.

| Layer | Library | Version | Rationale |
|-------|---------|---------|-----------|
| **Language** | Python | 3.11+ | Dataclasses, union types, speed improvements |
| **Claude API** | `anthropic` | >=0.40.0 | Official Anthropic SDK, streaming support |
| **CLI formatting** | `rich` | >=13.0 | Pretty tables, live streaming output panels |
| **CLI line editing** | `prompt_toolkit` | >=3.0 | Cross-platform arrow-key cursor editing + history at the prompt |
| **Env config** | `python-dotenv` | >=1.0 | Load `.env` file into `os.environ` on startup |
| **Memory** | `sqlite3` | stdlib | No extra dependency. WAL mode, FTS5 extension |
| **System metrics** | `psutil` | >=5.9 | Core dep — powers the `system_pulse` skill |
| **HTTP client** | `requests` | >=2.31 | Used for the Ollama fallback (local + cloud) |
| **Telegram adapter** | `python-telegram-bot` | >=21.0 | Optional. Async-first |
| **Discord adapter** | `discord.py` | >=2.3 | Optional. Async-first |
| **Web search** | `tavily-python` | >=0.5 | Optional — live web search for the `web_search` skill |
| **File output** | `python-docx`, `fpdf2` | >=1.1 / >=2.7 | Optional — `.docx` / `.pdf` output for `file_writer` |
| **Testing** | `pytest` | >=8.0 | Test suite |

> **Deviations from the original v1.0 plan:** the Ollama fallback uses
> `requests` (not `httpx`); `mypy`/`ruff`/`pytest-asyncio` are not pinned
> dependencies; and there is no TOML config file (see below).

### Configuration

ClawBro is configured entirely through **environment variables** loaded from a
`.env` file via `python-dotenv` — there is no `config.toml` and no `tomllib`
usage in the current build. CLI flags (`--model`, `--ollama`, `--adapter`,
`--db`, `--no-health-check`) override the corresponding env vars at launch. See
[Appendix B](#appendix-b-environment-variables) for the full variable list.

---

## 5. Skill Router Design

### Overview

The router is a simple, deterministic confidence scorer. It does NOT call the LLM to decide routing — that would be slow and expensive. Instead, each skill exposes a `score()` method that computes a confidence float based on the raw message text.

### Scoring Algorithm

```
CONFIDENCE_THRESHOLD = 0.4

def route(message: str) -> tuple[SkillBase, float]:
    best_skill, best_score = fallback_skill, 0.0
    for skill in registered_skills:
        score = skill.score(message)   # exceptions treated as 0.0
        if score > best_score:
            best_skill, best_score = skill, score

    if best_score >= CONFIDENCE_THRESHOLD:
        return (best_skill, best_score)
    return (fallback_skill, 0.0)
```

### Default `SkillBase.score()` Implementation

The base class provides a default implementation that skills can use or override:

```python
def score(self, message: str) -> float:
    """
    Default implementation: regex match counter with a fixed denominator.

    Algorithm:
    1. If the skill has no trigger_patterns, return 0.0.
    2. Lowercase the message.
    3. For each pattern in self.trigger_patterns, use re.search (patterns are
       regexes; plain strings work as literal regexes).
    4. Count matches and normalise: score = min(matches / 3.0, 1.0).
       So 2 hits → 0.67 (clears the 0.4 threshold), 3+ hits → 1.0.

    There is no start-of-message boost in the current implementation.
    """
```

### Skill Registration (at startup in main.py)

In the current build, `main.py` calls `get_all_skills()` (from `skills/__init__.py`)
and passes the list to the router constructor, which registers each in turn:

```python
from skills import get_all_skills
from skills.base import FallbackSkill

router = SkillRouter(skills=get_all_skills(), fallback=FallbackSkill())

# get_all_skills() returns one instance of each:
#   SystemArchitectSkill, KnowledgeSynthesizerSkill,
#   TechnicalProposalGeneratorSkill, DataRepurposerSkill,
#   SandboxGuardSkill, SystemPulseSkill, ResearchSummarizerSkill,
#   WebSearchSkill, FileWriterSkill
# FallbackSkill is passed separately and is never scored.
```

### Trigger Pattern Examples per Skill

> These are *illustrative*. The authoritative `trigger_patterns` live as a
> class attribute on each skill in `src/skills/*.py` and have drifted from the
> original list below (e.g. `SystemArchitectSkill` now also matches
> `"infrastructure"`, `"python script"`, `"hardware"`, etc.). Treat the source
> as the source of truth.

| Skill | trigger_patterns |
|-------|-----------------|
| `SystemArchitectSkill` | `["architect", "design system", "draw.*diagram", "system design", "infrastructure", "component diagram", "create.*script", "python script", "executable", "hardware", "utility script"]` |
| `KnowledgeSynthesizerSkill` | `["synthesize", "combine", "knowledge", "connect.*ideas", "link.*concepts"]` |
| `TechnicalProposalGeneratorSkill` | `["proposal", "technical spec", "write.*spec", "rfc", "technical document"]` |
| `DataRepurposerSkill` | `["repurpose", "reformat", "convert.*data", "transform.*data", "restructure"]` |
| `SandboxGuardSkill` | `["sandbox", "safe.*run", "isolate", "execute.*safely", "check.*security"]` |
| `SystemPulseSkill` | `["system.*status", "pulse", "health.*check", "disk.*usage", "cpu.*usage", "memory.*usage"]` |
| `ResearchSummarizerSkill` | `["summarize", "summary", "tldr", "research", "paper", "article.*summary"]` |
| `FileWriterSkill` | `["write.*file", "create.*file", "save.*(as\|to a file)", "export.*(as\|to)", "generate.*(file\|document)", "word doc", "docx", ".pdf", ".txt", ".md", ".csv", ".json", ".html", ...]` |
| `FallbackSkill` | `[]` — never scores; only used when all others score below threshold |

### Fallback Behavior

`FallbackSkill` wraps a plain Claude API call with no special system prompt additions. It is the general-purpose assistant. When it handles a turn it returns `SkillResult(text=response, skill_name="fallback", success=True)` — note it does not set a `confidence` metadata field; the router tracks confidence separately on the `ConversationContext`.

---

## 6. File Structure

```
claudeclaw v2/
├── src/                                  # ClawBro source root
│   ├── main.py                           # Entry point: parse args, init components, select adapter
│   │
│   ├── core/
│   │   ├── __init__.py                   # Re-exports core classes
│   │   ├── router.py                     # SkillRouter — dispatch logic, confidence scoring
│   │   ├── context.py                    # InputMessage, ConversationContext, TurnEvent dataclasses
│   │   └── claude_client.py              # ClaudeClient — streaming wrapper + Ollama fallback
│   │
│   ├── skills/
│   │   ├── __init__.py                   # Re-exports skills + get_all_skills()
│   │   ├── base.py                       # SkillBase ABC + FallbackSkill
│   │   ├── system_architect.py           # Skill: system design diagrams and architecture docs
│   │   ├── knowledge_synthesizer.py      # Skill: cross-domain knowledge linking and synthesis
│   │   ├── technical_proposal_generator.py  # Skill: RFC / technical spec writing
│   │   ├── data_repurposer.py            # Skill: data format conversion and restructuring
│   │   ├── sandbox_guard.py              # Skill: safe code execution analysis and sandboxing advice
│   │   ├── system_pulse.py               # Skill: system health metrics (disk, CPU, RAM via psutil)
│   │   ├── research_summarizer.py        # Skill: article/paper summarization and extraction
│   │   ├── web_search.py                 # Skill: live web search via Tavily, with cited sources
│   │   ├── file_writer.py                # Skill: generate content and write to .txt/.md/.csv/.json/.html/.docx/.pdf
│   │   └── fallback.py                   # Re-exports FallbackSkill from base.py (convenience import)
│   │
│   ├── memory/
│   │   ├── __init__.py                   # Re-exports MemoryStore + init_db
│   │   ├── init_db.py                    # Schema creation / migration
│   │   ├── short_term.py                 # ShortTermMemory — ring buffer + SQLite flush
│   │   ├── long_term.py                  # LongTermMemory — FTS5 key-value store
│   │   └── store.py                      # MemoryStore facade — unified API for skills
│   │
│   └── adapters/
│       ├── __init__.py                   # Re-exports adapter classes
│       ├── cli.py                        # CLIAdapter — rich prompt, streaming output renderer
│       ├── telegram_adapter.py           # TelegramAdapter — python-telegram-bot integration
│       └── discord_adapter.py            # DiscordAdapter — discord.py integration
│
├── tests/                                # pytest suite
├── architecture/architecture.md          # This document
├── .env.example                          # Config template
├── .gitignore
├── requirements.txt                      # Core + optional dependencies
├── README.md                             # User-facing overview
└── SETUP.md                              # Install & run guide
```

> **Note:** the canonical `FallbackSkill` is defined in `skills/base.py`. The
> `score()` default also lives in `SkillBase` (base.py), not a separate module.

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
| `skills/web_search.py` | Live web search via Tavily API, with inline citations |
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
| Pairing guard / access control | ZeroClaw `security/` | **Simplify** | CLI is local-only. The Telegram adapter additionally enforces a fail-closed `TELEGRAM_ALLOWED_USER_IDS` allowlist (rejects all if unset); Discord relies on bot-token auth |
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

**Scenario:** User types `"Give me a system design with a component diagram for a URL shortener"` at the CLI prompt.

---

**Step 1 — Adapter receives input**

`adapters/cli.py` reads the input string from the terminal via `rich`'s `console.input()`.

It constructs:
```python
InputMessage(
    text="Give me a system design with a component diagram for a URL shortener",
    source="cli",
    user_id="local",
    session_id="a1b2c3d4-...",   # UUID generated at session start
    timestamp=1744000000.0,
    metadata={}
)
```

---

**Step 2 — Router scores all skills**

`core/router.py` receives the `InputMessage`. The default `score()` lowercases
the text internally and runs `re.search` for each trigger pattern, dividing hits
by 3 (capped at 1.0):

| Skill | Pattern Hits | Score |
|-------|------------|-------|
| `SystemArchitectSkill` | `"system design"` + `"component diagram"` → 2/3 = **0.67** | 0.67 |
| `KnowledgeSynthesizerSkill` | no hit | 0.0 |
| `TechnicalProposalGeneratorSkill` | no hit | 0.0 |
| `DataRepurposerSkill` | no hit | 0.0 |
| `SandboxGuardSkill` | no hit | 0.0 |
| `SystemPulseSkill` | no hit | 0.0 |
| `ResearchSummarizerSkill` | no hit | 0.0 |

`SystemArchitectSkill` wins with 0.67 ≥ threshold 0.4.

Router returns `(SystemArchitectSkill, 0.67)`. (Note: a vaguer prompt like
"design me a system architecture" hits only one pattern → 0.33, below threshold,
and would route to the fallback assistant instead.)

---

**Step 3 — Context is prepared**

The adapter retrieves trimmed history, **writes the user turn to memory**, and
constructs a `ConversationContext`. (In the CLI adapter the user turn is recorded
*before* dispatch — see `_handle_message`.)

```python
# Retrieve trimmed history from MemoryStore, then record this user turn
history = memory_store.get_history()        # default budget 8000 tokens
memory_store.add_turn("user", input_message.text)

context = ConversationContext(
    message=input_message,
    history=history,
    memory=memory_store,
    claude=claude_client,
    skill_name="system_architect",   # set by router during dispatch()
    confidence=0.67,
    session_id="a1b2c3d4-..."
)
```

---

**Step 4 — Skill handles the request**

`router.dispatch()` calls `SystemArchitectSkill.handle(context)`. Inside (see
`skills/system_architect.py` for the real implementation):

1. Assembles the message list, prepending its skill-specific instructions as a
   leading user message rather than a separate `system=` argument:
   ```python
   messages = [
       {"role": "user", "content": _SYSTEM_PROMPT},   # "You are an expert systems architect..."
       *context.history,
       {"role": "user", "content": context.message.text},
   ]
   ```

2. Calls `context.claude.complete(messages)` — the non-streaming convenience
   wrapper that drains `stream()` and returns the full assembled text. (Skills in
   this build use `complete()`; token-by-token streaming via `stream()` is
   available but not currently used by the bundled skills.)

3. Returns:
   ```python
   SkillResult(
       text=artifact,
       skill_name="system_architect",
       success=True,
       metadata={"artifact_type": "script_or_diagram"},
   )
   ```

Note: skills do **not** write to memory themselves — the adapter records both the
user and assistant turns (see Steps 3 and 7). The router sets `skill_name` and
`confidence` on the context during `dispatch()`.

---

**Step 5 — Claude API call**

Inside `ClaudeClient.complete()` → `stream()` → `_stream_claude()`:

1. Calls `self._client.messages.stream(...)` with:
   - `model="claude-sonnet-4-6"` (or the per-call / env override)
   - `messages=[{"role": "user", "content": _SYSTEM_PROMPT}, ...history..., {user turn}]`
   - `max_tokens=2048` (the default for `complete()`)
   - `system=...` only if a non-empty system string was passed (skills here pass none)

2. For each event from the SDK stream:
   - text delta → `yield ChunkEvent(text=delta.text)`
   - thinking delta → `yield ThinkingEvent(text=delta.thinking)`
   - tool-use block start → `yield ToolCallEvent(tool_name=..., tool_use_id=...)`
   - stream end → `yield DoneEvent(full_text=assembled, input_tokens=..., output_tokens=...)`

   `complete()` collects the `ChunkEvent`/`DoneEvent` text and returns the final string.
   If `use_ollama` is set, the call is served from Ollama instead, falling back to
   Claude on a 401/403.

---

**Step 6 — Adapter renders output**

The CLI adapter prints a dim `(using: system_architect)` line before dispatch,
then renders the returned `SkillResult.text` (the `rich.Live` panel
infrastructure exists for token streaming, but the bundled skills return a
complete string via `complete()`).

---

**Step 7 — Memory persists the assistant turn**

The user turn was recorded in Step 3. After dispatch returns, the adapter records
the assistant turn with `MemoryStore.add_turn("assistant", result.text)`. Each
`add_turn` appends to the in-memory buffer and inserts a row into
`conversation_turns`:
```sql
INSERT INTO conversation_turns (session_id, role, content, timestamp)
VALUES ('a1b2c3d4-...', 'user', 'Give me a system design...', 1744000000.0);

INSERT INTO conversation_turns (session_id, role, content, timestamp)
VALUES ('a1b2c3d4-...', 'assistant', '```mermaid\n...', 1744000010.0);
```

The next user turn retrieves these rows via `get_history()`, so the model has
full context of the prior exchange.

---

**Full sequence summary:**

```
CLI input
  → InputMessage construction          [adapters/cli.py]
    → MemoryStore.get_history()        [memory/store.py → short_term.py]
    → MemoryStore.add_turn("user", …)  [memory/store.py]
    → SkillRouter.route()              [core/router.py]
      → skill.score() × N             [skills/*.py]
    → SkillRouter.dispatch()           [core/router.py]
      → (sets context.skill_name / confidence)
      → SystemArchitectSkill.handle()  [skills/system_architect.py]
        → ClaudeClient.complete()      [core/claude_client.py]
          → stream() → _stream_claude()
            → anthropic SDK (streaming) [external]
            → yield TurnEvent*          [core/context.py]
        → return SkillResult           [skills/system_architect.py]
    → CLIAdapter renders SkillResult   [adapters/cli.py]
    → MemoryStore.add_turn("assistant", …)  [memory/store.py]
```

---

## Appendix A: SQLite Schema

This is the actual DDL from `src/memory/__init__.py` (`init_db` is idempotent —
every statement uses `IF NOT EXISTS`).

```sql
-- Conversation history (short-term, session-scoped)
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

-- Long-term fact store
CREATE TABLE IF NOT EXISTS long_term_memory (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    metadata   TEXT DEFAULT '{}',
    created_at REAL DEFAULT (unixepoch('now', 'subsec')),
    updated_at REAL DEFAULT (unixepoch('now', 'subsec'))
);

-- FTS5 index on long_term_memory
CREATE VIRTUAL TABLE IF NOT EXISTS long_term_memory_fts
    USING fts5(key, value, content='long_term_memory', content_rowid='rowid');

-- Triggers to keep FTS5 in sync
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
```

---

## Appendix B: Environment Variables

These reflect the variables actually read in `src/main.py` (via `python-dotenv`).

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes* | — | Anthropic API key (*not required in Ollama-only mode) |
| `CLAUDE_MODEL` | No | `claude-sonnet-4-6` | Override default Claude model |
| `CLAUDE_MAX_TOKENS` | No | `2048` | Max tokens per response |
| `CLAWBRO_DB_PATH` | No | `~/.clawbro/memory.db` | Override SQLite database path |
| `CLAWBRO_LOG_PATH` | No | `~/.clawbro/clawbro.log` | Override log file path |
| `TELEGRAM_BOT_TOKEN` | No | — | Required to run the Telegram adapter |
| `TELEGRAM_ALLOWED_USER_IDS` | No | — | Comma-separated allowlist; bot fails closed if unset |
| `DISCORD_BOT_TOKEN` | No | — | Required to run the Discord adapter |
| `TAVILY_API_KEY` | No | — | Enables the `web_search` skill (tavily.com) |
| `OLLAMA_ENABLED` | No | `false` | Route to Ollama instead of Claude |
| `OLLAMA_MODEL` | No | `llama3` | Ollama model name |
| `OLLAMA_HOST` | No | `http://localhost:11434` | Ollama endpoint |
| `OLLAMA_API_KEY` | No | — | Required for cloud-hosted Ollama models |

---

## Appendix C: `requirements.txt` (Pinned)

See [`requirements.txt`](../requirements.txt) for the authoritative list. As built:

```
# Core (always required)
anthropic>=0.40.0        # Claude API client (streaming)
python-dotenv>=1.0.0     # Loads .env into the environment
rich>=13.0.0             # Terminal formatting for the CLI
prompt_toolkit>=3.0.0    # Arrow-key line editing + history in the CLI prompt
requests>=2.31.0         # HTTP client for the Ollama fallback
psutil>=5.9.0            # System metrics for the system_pulse skill

# Optional: chat adapters
python-telegram-bot>=21.0
discord.py>=2.3.0

# Optional: web_search skill
tavily-python>=0.5.0     # Tavily API client (needs TAVILY_API_KEY)

# Optional: file_writer output formats
python-docx>=1.1.0       # .docx output
fpdf2>=2.7.0             # .pdf output

# Dev / Testing
pytest>=8.0.0
```

> **Note:** the Ollama fallback uses `requests`, not `httpx`. `psutil` is a core
> dependency because the `system_pulse` skill needs it. Config is read from
> environment variables only — there is no `config.toml` or `tomllib` usage in
> the current build.

---

*This document is the binding architecture specification for ClawBro v1.0. All implementation decisions in `outputs/src/` must trace back to a section in this document. Deviations require a documented rationale and an update to the relevant section.*
