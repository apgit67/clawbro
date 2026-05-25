"""
core/router.py
--------------
SkillRouter: scores all registered skills against an incoming message and
dispatches to the winner, falling back to FallbackSkill when no skill
clears CONFIDENCE_THRESHOLD.
"""

from __future__ import annotations

import logging

from core.context import ConversationContext, InputMessage, SkillResult
from skills.base import FallbackSkill, SkillBase

logger = logging.getLogger(__name__)


class SkillRouter:
    """
    Routes an InputMessage to the most-confident registered skill.

    Usage
    -----
    ::

        router = SkillRouter(skills=get_all_skills(), fallback=FallbackSkill())
        skill, confidence = router.route(message.text)
        result = router.dispatch(message, context)
    """

    CONFIDENCE_THRESHOLD: float = 0.4

    def __init__(self, skills: list[SkillBase], fallback: SkillBase) -> None:
        """
        Parameters
        ----------
        skills:
            Ordered list of candidate skills.  All are scored on every call;
            order only matters as a tie-breaker (first registered wins).
        fallback:
            Skill to use when no candidate clears CONFIDENCE_THRESHOLD.
        """
        self._skills: list[SkillBase] = []
        self._fallback: SkillBase = fallback

        for skill in skills:
            self.register(skill)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, skill: SkillBase) -> None:
        """Add a skill to the router's candidate pool."""
        if not isinstance(skill, SkillBase):
            raise TypeError(
                f"Expected a SkillBase instance, got {type(skill).__name__!r}"
            )
        self._skills.append(skill)
        logger.debug("Registered skill: %s (v%s)", skill.name, skill.version)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def route(self, message: str) -> tuple[SkillBase, float]:
        """
        Score every registered skill against *message* and return the
        (skill, confidence) pair with the highest score.

        If no skill's score reaches CONFIDENCE_THRESHOLD, the fallback
        skill is returned with confidence 0.0.

        Parameters
        ----------
        message:
            Raw user message text to route.

        Returns
        -------
        tuple[SkillBase, float]
            The selected skill and its confidence score.
        """
        best_skill: SkillBase = self._fallback
        best_score: float = 0.0

        for skill in self._skills:
            try:
                score = skill.score(message)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skill %r raised an exception during score(): %s",
                    skill.name,
                    exc,
                )
                score = 0.0

            logger.debug("Skill %r scored %.3f", skill.name, score)

            if score > best_score:
                best_score = score
                best_skill = skill

        if best_score < self.CONFIDENCE_THRESHOLD:
            logger.info(
                "No skill cleared threshold %.2f (best: %r @ %.3f) -- using fallback.",
                self.CONFIDENCE_THRESHOLD,
                best_skill.name,
                best_score,
            )
            return self._fallback, 0.0

        logger.info(
            "Routing to %r with confidence %.3f.", best_skill.name, best_score
        )
        return best_skill, best_score

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch(
        self,
        message: InputMessage,
        context: ConversationContext,
    ) -> SkillResult:
        """
        Route *message*, update *context* with the selected skill's metadata,
        then call skill.handle(context) and return the result.

        Parameters
        ----------
        message:
            The inbound InputMessage.
        context:
            A ConversationContext pre-populated by the caller; ``skill_name``
            and ``confidence`` are overwritten here.

        Returns
        -------
        SkillResult
        """
        skill, confidence = self.route(message.text)

        # Mutate context to reflect the routing decision
        context.skill_name = skill.name
        context.confidence = confidence

        try:
            result = skill.handle(context)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Unhandled exception in skill %r: %s", skill.name, exc, exc_info=True
            )
            result = SkillResult(
                text=f"[{skill.name}] Unexpected error: {exc}",
                skill_name=skill.name,
                success=False,
                error_message=str(exc),
            )

        return result

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_skills(self) -> list[dict]:
        """Return metadata for all registered skills plus the fallback.

        Returns
        -------
        list[dict]
            Each dict has keys: ``name``, ``description``, ``version``.
        """
        result = []
        for skill in self._skills:
            result.append({
                "name": skill.name,
                "description": skill.description,
                "version": getattr(skill, "version", "1.0.0"),
            })
        result.append({
            "name": self._fallback.name,
            "description": self._fallback.description,
            "version": getattr(self._fallback, "version", "1.0.0"),
        })
        return result
