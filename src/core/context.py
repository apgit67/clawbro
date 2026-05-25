"""
core/context.py
---------------
Data classes for ClawBro's message pipeline and skill system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from core.claude_client import ClaudeClient
    from memory.store import MemoryStore


# ---------------------------------------------------------------------------
# Input / message layer
# ---------------------------------------------------------------------------

@dataclass
class InputMessage:
    """Represents a single inbound message from any supported source."""

    text: str
    source: str          # "cli" | "telegram" | "discord"
    user_id: str
    session_id: str
    timestamp: float
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Streaming event types
# ---------------------------------------------------------------------------

@dataclass
class ChunkEvent:
    kind: Literal["chunk"] = "chunk"
    text: str = ""


@dataclass
class ThinkingEvent:
    kind: Literal["thinking"] = "thinking"
    text: str = ""


@dataclass
class ToolCallEvent:
    kind: Literal["tool_call"] = "tool_call"
    tool_name: str = ""
    tool_input: dict = None
    tool_use_id: str = ""


@dataclass
class ToolResultEvent:
    kind: Literal["tool_result"] = "tool_result"
    tool_use_id: str = ""
    result: Any = None
    is_error: bool = False


@dataclass
class DoneEvent:
    kind: Literal["done"] = "done"
    full_text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""


# Union of all possible turn events
TurnEvent = ChunkEvent | ThinkingEvent | ToolCallEvent | ToolResultEvent | DoneEvent


# ---------------------------------------------------------------------------
# Skill result & conversation context
# ---------------------------------------------------------------------------

@dataclass
class SkillResult:
    """The structured result returned by any skill's handle() method."""

    text: str
    skill_name: str
    success: bool = True
    error_message: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ConversationContext:
    """
    Full context passed into every skill's handle() method.

    Attributes
    ----------
    message:
        The raw inbound message being processed.
    history:
        List of prior conversation turns (each a dict with ``role`` and
        ``content`` keys compatible with the Claude messages API).
    memory:
        Reference to the shared MemoryStore for reading/writing persistent data.
    claude:
        Reference to the ClaudeClient; skills should call
        ``context.claude.complete(messages)`` for inference.
    skill_name:
        Name of the skill that was selected to handle this turn.
    confidence:
        Router confidence score that led to this skill being selected.
    session_id:
        Stable identifier for the current conversation session.
    """

    message: InputMessage
    history: list[dict]
    memory: "MemoryStore"
    claude: "ClaudeClient"
    skill_name: str
    confidence: float
    session_id: str
