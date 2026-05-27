"""
tests/test_skills.py
---------------------
Unit tests for all ClawBro skills.

Tests:
- Each skill's score() returns > 0.4 for representative messages
- Each skill's score() returns < 0.4 for irrelevant messages
- SkillRouter routes correctly for sample messages
- FallbackSkill.score() always returns 0.0

No Claude API key required — handle() is not called here.

Run with:
    cd outputs/
    pytest tests/test_skills.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from skills.base import FallbackSkill, SkillBase, SkillResult  # noqa: E402
from skills.system_architect import SystemArchitectSkill  # noqa: E402
from skills.knowledge_synthesizer import KnowledgeSynthesizerSkill  # noqa: E402
from skills.technical_proposal_generator import TechnicalProposalGeneratorSkill  # noqa: E402
from skills.data_repurposer import DataRepurposerSkill  # noqa: E402
from skills.sandbox_guard import SandboxGuardSkill  # noqa: E402
from skills.system_pulse import SystemPulseSkill  # noqa: E402
from skills.research_summarizer import ResearchSummarizerSkill  # noqa: E402
from skills.web_search import WebSearchSkill  # noqa: E402
from skills import get_all_skills  # noqa: E402
from core.router import SkillRouter  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score(skill: SkillBase, msg: str) -> float:
    return skill.score(msg)


# ---------------------------------------------------------------------------
# FallbackSkill
# ---------------------------------------------------------------------------

class TestFallbackSkill:
    def setup_method(self):
        self.skill = FallbackSkill()

    def test_score_always_zero_general(self):
        assert self.skill.score("anything at all") == 0.0

    def test_score_always_zero_empty(self):
        assert self.skill.score("") == 0.0

    def test_score_always_zero_matching_other_skills(self):
        # Even if it looks like it matches another skill's keywords, stays 0
        assert self.skill.score("design me a system architect blueprint") == 0.0

    def test_name(self):
        assert self.skill.name == "fallback"


# ---------------------------------------------------------------------------
# SystemArchitectSkill
# ---------------------------------------------------------------------------

class TestSystemArchitectSkill:
    def setup_method(self):
        self.skill = SystemArchitectSkill()

    @pytest.mark.parametrize("msg", [
        "design system architect blueprint and draw component diagram",
        "create a python script for infrastructure automation",
        "draw a component diagram for system design",
        "write an executable python script to automate backups",
        "infrastructure design system for a web application",
    ])
    def test_score_high_for_relevant(self, msg):
        assert _score(self.skill, msg) >= 0.4, f"Expected >= 0.4 for: {msg!r}"

    @pytest.mark.parametrize("msg", [
        "what are the islands in Hawaii",
        "convert this CSV to JSON",
        "how much RAM is my computer using",
        "remember that my project uses port 8080",
    ])
    def test_score_low_for_irrelevant(self, msg):
        assert _score(self.skill, msg) < 0.4, f"Expected < 0.4 for: {msg!r}"


# ---------------------------------------------------------------------------
# KnowledgeSynthesizerSkill
# ---------------------------------------------------------------------------

class TestKnowledgeSynthesizerSkill:
    def setup_method(self):
        self.skill = KnowledgeSynthesizerSkill()

    @pytest.mark.parametrize("msg", [
        "synthesize this raw data into a polished technical document",
        "process this PDF extract from data into a knowledge base",
        "create a polished technical document from raw data",
        "synthesize knowledge base from extracted raw data",
    ])
    def test_score_high_for_relevant(self, msg):
        assert _score(self.skill, msg) >= 0.4, f"Expected >= 0.4 for: {msg!r}"

    @pytest.mark.parametrize("msg", [
        "what is the capital of France",
        "design a system for authentication",
        "dry run this Python script",
    ])
    def test_score_low_for_irrelevant(self, msg):
        assert _score(self.skill, msg) < 0.4, f"Expected < 0.4 for: {msg!r}"


# ---------------------------------------------------------------------------
# TechnicalProposalGeneratorSkill
# ---------------------------------------------------------------------------

class TestTechnicalProposalGeneratorSkill:
    def setup_method(self):
        self.skill = TechnicalProposalGeneratorSkill()

    @pytest.mark.parametrize("msg", [
        "write a technical proposal and statement of work for a new payment gateway",
        "draft a statement of work with technical spec and scope for the mobile app",
        "create a project blueprint proposal with scope and requirements doc",
        "generate a technical spec proposal for our API redesign blueprint",
    ])
    def test_score_high_for_relevant(self, msg):
        assert _score(self.skill, msg) >= 0.4, f"Expected >= 0.4 for: {msg!r}"

    @pytest.mark.parametrize("msg", [
        "tell me about machine learning",
        "what is my CPU usage",
        "convert markdown to HTML",
    ])
    def test_score_low_for_irrelevant(self, msg):
        assert _score(self.skill, msg) < 0.4, f"Expected < 0.4 for: {msg!r}"


# ---------------------------------------------------------------------------
# DataRepurposerSkill
# ---------------------------------------------------------------------------

class TestDataRepurposerSkill:
    def setup_method(self):
        self.skill = DataRepurposerSkill()

    @pytest.mark.parametrize("msg", [
        "convert and transform this CSV to JSON format",
        "transform and repurpose this markdown to HTML",
        "convert this from XML to YAML and change format",
        "repurpose and transform this data from CSV to JSON",
    ])
    def test_score_high_for_relevant(self, msg):
        assert _score(self.skill, msg) >= 0.4, f"Expected >= 0.4 for: {msg!r}"

    @pytest.mark.parametrize("msg", [
        "design a microservice architecture",
        "summarize this research paper",
        "what are system health metrics",
    ])
    def test_score_low_for_irrelevant(self, msg):
        assert _score(self.skill, msg) < 0.4, f"Expected < 0.4 for: {msg!r}"


# ---------------------------------------------------------------------------
# SandboxGuardSkill
# ---------------------------------------------------------------------------

class TestSandboxGuardSkill:
    def setup_method(self):
        self.skill = SandboxGuardSkill()

    @pytest.mark.parametrize("msg", [
        "dry-run this Python script and sandbox validate before I execute it",
        "sandbox check: test script and validate it is safe to run",
        "dry run and validate this script is safe to run on my system",
        "sandbox dry-run: will this script break anything? check code safety",
    ])
    def test_score_high_for_relevant(self, msg):
        assert _score(self.skill, msg) >= 0.4, f"Expected >= 0.4 for: {msg!r}"

    @pytest.mark.parametrize("msg", [
        "explain quantum computing",
        "draft a project proposal",
        "how much memory is my system using",
    ])
    def test_score_low_for_irrelevant(self, msg):
        assert _score(self.skill, msg) < 0.4, f"Expected < 0.4 for: {msg!r}"


# ---------------------------------------------------------------------------
# SystemPulseSkill
# ---------------------------------------------------------------------------

class TestSystemPulseSkill:
    def setup_method(self):
        self.skill = SystemPulseSkill()

    @pytest.mark.parametrize("msg", [
        "show system health metrics and cpu performance report",
        "how much CPU is used and what are memory usage metrics",
        "check memory usage and disk space performance metrics",
        "give me a system pulse health report with cpu metrics",
        "system health performance metrics and disk space status",
    ])
    def test_score_high_for_relevant(self, msg):
        assert _score(self.skill, msg) >= 0.4, f"Expected >= 0.4 for: {msg!r}"

    @pytest.mark.parametrize("msg", [
        "write a project proposal",
        "convert CSV to JSON",
        "explain neural networks",
    ])
    def test_score_low_for_irrelevant(self, msg):
        assert _score(self.skill, msg) < 0.4, f"Expected < 0.4 for: {msg!r}"


# ---------------------------------------------------------------------------
# ResearchSummarizerSkill
# ---------------------------------------------------------------------------

class TestResearchSummarizerSkill:
    def setup_method(self):
        self.skill = ResearchSummarizerSkill()

    @pytest.mark.parametrize("msg", [
        "research and summarize the history of quantum computing and explain it",
        "tell me about and explain the islands in Hawaii",
        "look up and explain how transformer neural networks work",
        "research and find information about the Rust programming language and summarize",
        "what is and explain retrieval-augmented generation, tell me about it",
    ])
    def test_score_high_for_relevant(self, msg):
        assert _score(self.skill, msg) >= 0.4, f"Expected >= 0.4 for: {msg!r}"

    @pytest.mark.parametrize("msg", [
        "dry run this Python script",
        "generate a project statement of work",
    ])
    def test_score_low_for_irrelevant(self, msg):
        assert _score(self.skill, msg) < 0.4, f"Expected < 0.4 for: {msg!r}"


class TestWebSearchSkill:
    def setup_method(self):
        self.skill = WebSearchSkill()

    @pytest.mark.parametrize("msg", [
        "what's the latest news on the election",
        "what is the current price of bitcoin",
        "search the web for today's weather in Tokyo",
        "who won the game tonight",
        "find out what's happening with the latest iPhone release",
    ])
    def test_score_high_for_relevant(self, msg):
        assert _score(self.skill, msg) >= 0.4, f"Expected >= 0.4 for: {msg!r}"

    @pytest.mark.parametrize("msg", [
        "explain how a hash map works",
        "write a Python function to reverse a string",
    ])
    def test_score_low_for_irrelevant(self, msg):
        assert _score(self.skill, msg) < 0.4, f"Expected < 0.4 for: {msg!r}"


# ---------------------------------------------------------------------------
# get_all_skills() — registry
# ---------------------------------------------------------------------------

class TestSkillRegistry:
    def test_returns_all_skills(self):
        skills = get_all_skills()
        assert len(skills) == 9

    def test_all_are_skillbase_instances(self):
        for skill in get_all_skills():
            assert isinstance(skill, SkillBase)

    def test_no_fallback_in_list(self):
        for skill in get_all_skills():
            assert not isinstance(skill, FallbackSkill)

    def test_unique_names(self):
        names = [s.name for s in get_all_skills()]
        assert len(names) == len(set(names)), "Duplicate skill names found"


# ---------------------------------------------------------------------------
# SkillRouter
# ---------------------------------------------------------------------------

class TestSkillRouter:
    def setup_method(self):
        self.fallback = FallbackSkill()
        self.router = SkillRouter(skills=get_all_skills(), fallback=self.fallback)

    def test_routes_system_pulse(self):
        skill, score = self.router.route("check my CPU usage and disk space performance metrics")
        assert skill.name == "system_pulse", f"Got {skill.name!r} instead"
        assert score >= 0.4

    def test_routes_sandbox_guard(self):
        skill, score = self.router.route("dry-run this script in sandbox before executing it")
        assert skill.name == "sandbox_guard", f"Got {skill.name!r} instead"
        assert score >= 0.4

    def test_routes_data_repurposer(self):
        skill, score = self.router.route("convert and transform this CSV file to JSON format")
        assert skill.name == "data_repurposer", f"Got {skill.name!r} instead"
        assert score >= 0.4

    def test_routes_technical_proposal(self):
        skill, score = self.router.route("write a technical proposal and statement of work for this project blueprint")
        assert skill.name == "technical_proposal_generator", f"Got {skill.name!r} instead"
        assert score >= 0.4

    def test_falls_back_for_unknown(self):
        skill, score = self.router.route("xyzzy frobble wumpus blorb")
        assert skill.name == "fallback"
        assert score == 0.0

    def test_dispatch_returns_skill_result(self):
        """dispatch() should return a SkillResult even when skill.handle() raises."""
        from unittest.mock import MagicMock, patch
        import time, uuid
        from core.context import ConversationContext, InputMessage

        # Use a message that reliably routes to system_pulse (2+ pattern hits)
        msg = InputMessage(
            text="check my CPU usage and disk space performance metrics",
            source="cli",
            user_id="test",
            session_id=str(uuid.uuid4()),
            timestamp=time.time(),
        )
        mock_memory = MagicMock()
        mock_memory.session_id = msg.session_id
        mock_memory.get_history.return_value = []
        mock_claude = MagicMock()

        ctx = ConversationContext(
            message=msg,
            history=[],
            memory=mock_memory,
            claude=mock_claude,
            skill_name="",
            confidence=0.0,
            session_id=msg.session_id,
        )

        # Patch handle() on the selected skill to raise so we test error path
        with patch.object(SystemPulseSkill, "handle", side_effect=RuntimeError("boom")):
            result = self.router.dispatch(msg, ctx)

        assert isinstance(result, SkillResult)
        assert result.success is False

    def test_register_raises_on_non_skill(self):
        with pytest.raises(TypeError):
            self.router.register("not_a_skill")  # type: ignore[arg-type]

    def test_list_skills_includes_all(self):
        listed = self.router.list_skills()
        names = {s["name"] for s in listed}
        assert "fallback" in names
        assert "web_search" in names
        assert len(listed) == 10  # 9 skills + fallback
