"""
skills/base.py
--------------
Abstract base class for all ClawBro skills, plus the FallbackSkill.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from core.context import ConversationContext, SkillResult


class SkillBase(ABC):
    """
    Every skill must subclass SkillBase and implement ``score()`` and
    ``handle()``.

    Class-level attributes
    ----------------------
    name:
        Unique snake_case identifier for this skill.
    description:
        Human-readable one-liner shown in help output.
    version:
        Semver string, e.g. "1.0.0".
    trigger_patterns:
        List of regex patterns (case-insensitive) used by the default
        ``score()`` implementation.  Override ``score()`` for more
        sophisticated matching.
    """

    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    trigger_patterns: list[str] = []

    # ------------------------------------------------------------------
    # Default scoring — subclasses may override for richer logic
    # ------------------------------------------------------------------

    def score(self, message: str) -> float:
        """
        Count how many ``trigger_patterns`` match the lower-cased message,
        then normalise to [0, 1].

        Normalisation uses a fixed denominator of 3 so that skills with many
        patterns are not penalised — matching 2 patterns always clears the
        router's 0.4 threshold, and 3+ matches saturates to 1.0.

        Returns 0.0 immediately if there are no trigger patterns.
        """
        if not self.trigger_patterns:
            return 0.0

        lowered = message.lower()
        hits = sum(
            1
            for pattern in self.trigger_patterns
            if re.search(pattern, lowered)
        )
        return min(hits / 3.0, 1.0)

    # ------------------------------------------------------------------
    # Handle — must be implemented by every skill
    # ------------------------------------------------------------------

    @abstractmethod
    def handle(self, context: ConversationContext) -> SkillResult:
        """Process the request and return a SkillResult."""
        ...

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _error_result(self, error_message: str) -> SkillResult:
        """Convenience helper to build a failure SkillResult."""
        return SkillResult(
            text=f"[{self.name}] Error: {error_message}",
            skill_name=self.name,
            success=False,
            error_message=error_message,
        )


class FallbackSkill(SkillBase):
    """
    Catch-all skill used when no other skill clears the confidence
    threshold.  It forwards the user's message directly to Claude as a
    general assistant query.
    """

    name = "fallback"
    description = "General-purpose Claude assistant (fallback handler)."
    version = "1.0.0"
    trigger_patterns = []  # intentionally empty — never self-selects

    def score(self, message: str) -> float:  # noqa: ARG002
        """Always returns 0.0 so the router only picks this as a last resort."""
        return 0.0

    def handle(self, context: ConversationContext) -> SkillResult:
        """Forward the user's message to Claude with no extra framing."""
        try:
            messages = [
                *context.history,
                {"role": "user", "content": context.message.text},
            ]
            response = context.claude.complete(messages)
            return SkillResult(
                text=response,
                skill_name=self.name,
                success=True,
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_result(str(exc))
