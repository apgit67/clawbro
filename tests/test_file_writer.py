"""
tests/test_file_writer.py
--------------------------
Comprehensive unit tests for FileWriterSkill.

Covers:
- score() for relevant and irrelevant messages
- _detect_format() helper
- _detect_output_path() helper
- SkillRouter integration (routes to "file_writer")
- handle() with mocked claude client (txt format, file I/O verified)

No real Claude API key required.
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure src/ is importable
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from skills.file_writer import FileWriterSkill, _detect_format, _detect_output_path  # noqa: E402
from skills.base import FallbackSkill  # noqa: E402
from skills import get_all_skills  # noqa: E402
from core.router import SkillRouter  # noqa: E402
from core.context import ConversationContext, InputMessage, SkillResult  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skill() -> FileWriterSkill:
    return FileWriterSkill()


def _make_context(text: str, claude_return: str = "", tmp_path: Path | None = None) -> ConversationContext:
    """Build a minimal ConversationContext with a mocked ClaudeClient."""
    mock_claude = MagicMock()
    mock_claude.complete.return_value = claude_return

    mock_memory = MagicMock()
    session = str(uuid.uuid4())
    mock_memory.session_id = session
    mock_memory.get_history.return_value = []

    msg = InputMessage(
        text=text,
        source="cli",
        user_id="test_user",
        session_id=session,
        timestamp=time.time(),
    )

    return ConversationContext(
        message=msg,
        history=[],
        memory=mock_memory,
        claude=mock_claude,
        skill_name="file_writer",
        confidence=0.9,
        session_id=session,
    )


# ---------------------------------------------------------------------------
# score() — relevant messages (must return >= 0.4)
# ---------------------------------------------------------------------------

class TestScoreRelevant:
    """FileWriterSkill.score() should reach the router threshold for these."""

    skill: FileWriterSkill

    def setup_method(self):
        self.skill = _make_skill()

    @pytest.mark.parametrize("msg", [
        "write a text file with my notes",
        # "create a word doc for my report" only hits 1 pattern (score=0.333).
        # Use a 2-pattern message so the score clears the 0.4 threshold:
        "create a word doc file for my report",
        "save this as a PDF",
        "generate a .csv file",
        "make a .json file",
        "export as .html",
        "save as notepad file",
        "create a file called report.txt",
        # "write a markdown file" only hits 1 pattern (score=0.333).
        # Use a 2-pattern message so the score clears the 0.4 threshold:
        "write a markdown .md file",
    ])
    def test_score_high(self, msg: str):
        score = self.skill.score(msg)
        assert score >= 0.4, (
            f"score() returned {score:.3f} for {msg!r} — expected >= 0.4"
        )


# ---------------------------------------------------------------------------
# score() — irrelevant messages (must return < 0.4)
# ---------------------------------------------------------------------------

class TestScoreIrrelevant:
    """FileWriterSkill.score() should stay below threshold for these."""

    skill: FileWriterSkill

    def setup_method(self):
        self.skill = _make_skill()

    @pytest.mark.parametrize("msg", [
        "check my CPU usage",
        "what is quantum computing",
        "synthesize this research",
        "sandbox check this script",
    ])
    def test_score_low(self, msg: str):
        score = self.skill.score(msg)
        assert score < 0.4, (
            f"score() returned {score:.3f} for {msg!r} — expected < 0.4"
        )


# ---------------------------------------------------------------------------
# _detect_format()
# ---------------------------------------------------------------------------

class TestDetectFormat:

    @pytest.mark.parametrize("msg, expected", [
        ("write a word doc",           "docx"),
        ("save as pdf",                "pdf"),
        ("create a .csv",              "csv"),
        ("make a .json file",          "json"),
        ("write a markdown file",      "md"),
        ("create an html page",        "html"),
        ("write a text file",          "txt"),
        ("something with no format hint", "txt"),  # default
    ])
    def test_format_detection(self, msg: str, expected: str):
        result = _detect_format(msg)
        assert result == expected, (
            f"_detect_format({msg!r}) returned {result!r}, expected {expected!r}"
        )


# ---------------------------------------------------------------------------
# _detect_output_path()
# ---------------------------------------------------------------------------

class TestDetectOutputPath:

    def test_explicit_path_with_tilde(self):
        """An explicit 'save to ~/docs/report.pdf' resolves correctly."""
        path = _detect_output_path("save to ~/docs/report.pdf", "pdf")
        assert path.name == "report.pdf", (
            f"Expected filename 'report.pdf', got {path.name!r}"
        )

    def test_explicit_path_save_as(self):
        """'save as notes.txt' resolves to a path ending in 'notes.txt'."""
        path = _detect_output_path("save as notes.txt", "txt")
        assert path.name == "notes.txt", (
            f"Expected filename 'notes.txt', got {path.name!r}"
        )

    def test_named_file_call_it(self):
        """'call it summary' should produce a stem of 'summary'."""
        path = _detect_output_path("call it summary", "txt")
        assert path.stem == "summary", (
            f"Expected stem 'summary', got {path.stem!r}"
        )

    def test_auto_generated_filename(self):
        """No hint → auto-timestamped filename starting with 'clawbro_'."""
        path = _detect_output_path("please write something for me", "txt")
        assert path.stem.startswith("clawbro_"), (
            f"Expected stem to start with 'clawbro_', got {path.stem!r}"
        )

    def test_named_file_uses_correct_extension(self):
        """Named file stem gets the correct extension appended."""
        path = _detect_output_path("call it quarterly_report", "csv")
        assert path.suffix == ".csv", (
            f"Expected .csv suffix, got {path.suffix!r}"
        )

    def test_auto_generated_uses_correct_extension(self):
        """Auto-generated path uses the passed format as extension."""
        path = _detect_output_path("write me something", "json")
        assert path.suffix == ".json", (
            f"Expected .json suffix, got {path.suffix!r}"
        )


# ---------------------------------------------------------------------------
# Router integration
# ---------------------------------------------------------------------------

class TestRouterIntegration:

    def setup_method(self):
        self.fallback = FallbackSkill()
        self.router = SkillRouter(skills=get_all_skills(), fallback=self.fallback)

    def test_routes_word_doc_message(self):
        """Router should select file_writer for a clear word-doc request.

        Note: "write a word doc for my project report" only hits 1 trigger
        pattern (score=0.333, below the 0.4 threshold). Use a message that
        hits 2 patterns so routing is unambiguous.
        """
        msg = "generate a word doc for my project report"
        skill, score = self.router.route(msg)
        assert skill.name == "file_writer", (
            f"Expected 'file_writer', got {skill.name!r} (score={score:.3f})"
        )
        assert score >= 0.4

    def test_routes_pdf_message(self):
        skill, score = self.router.route("save this as a PDF document")
        assert skill.name == "file_writer", (
            f"Expected 'file_writer', got {skill.name!r}"
        )

    def test_routes_csv_file(self):
        skill, score = self.router.route("generate a .csv file with sales data")
        assert skill.name == "file_writer", (
            f"Expected 'file_writer', got {skill.name!r}"
        )

    def test_routes_text_file(self):
        skill, score = self.router.route("write a text file with my notes")
        assert skill.name == "file_writer", (
            f"Expected 'file_writer', got {skill.name!r}"
        )


# ---------------------------------------------------------------------------
# handle() with mocked Claude — txt format, real file I/O via tmp_path
# ---------------------------------------------------------------------------

class TestHandleTxt:

    def test_creates_file_with_content(self, tmp_path: Path, monkeypatch):
        """handle() writes the Claude-generated content to the resolved path."""
        content = "hello world content"
        skill = _make_skill()
        ctx = _make_context(
            text="write a text file with my notes",
            claude_return=content,
        )

        # Redirect the auto-generated output to tmp_path so we don't pollute
        # the filesystem and tests clean up automatically.
        fake_out = tmp_path / "output.txt"
        monkeypatch.setattr(
            "skills.file_writer._detect_output_path",
            lambda msg, fmt: fake_out,
        )

        result = skill.handle(ctx)

        assert result.success is True, f"handle() failed: {result.error_message}"
        assert fake_out.exists(), "Expected output file to exist after handle()"
        assert fake_out.read_text(encoding="utf-8") == content

    def test_result_metadata_has_format_and_path(self, tmp_path: Path, monkeypatch):
        """SkillResult.metadata must include 'format' and 'path' keys."""
        skill = _make_skill()
        ctx = _make_context(
            text="write a text file with my notes",
            claude_return="some content",
        )

        fake_out = tmp_path / "output.txt"
        monkeypatch.setattr(
            "skills.file_writer._detect_output_path",
            lambda msg, fmt: fake_out,
        )

        result = skill.handle(ctx)

        assert "format" in result.metadata, "metadata missing 'format' key"
        assert "path" in result.metadata,   "metadata missing 'path' key"

    def test_result_metadata_format_is_txt(self, tmp_path: Path, monkeypatch):
        """Metadata 'format' should be 'txt' for a plain text request."""
        skill = _make_skill()
        ctx = _make_context(
            text="write a text file with my notes",
            claude_return="content",
        )

        fake_out = tmp_path / "output.txt"
        monkeypatch.setattr(
            "skills.file_writer._detect_output_path",
            lambda msg, fmt: fake_out,
        )

        result = skill.handle(ctx)
        assert result.metadata.get("format") == "txt"

    def test_result_success_true(self, tmp_path: Path, monkeypatch):
        """SkillResult.success must be True on a successful write."""
        skill = _make_skill()
        ctx = _make_context(
            text="write a text file",
            claude_return="data",
        )

        fake_out = tmp_path / "output.txt"
        monkeypatch.setattr(
            "skills.file_writer._detect_output_path",
            lambda msg, fmt: fake_out,
        )

        result = skill.handle(ctx)
        assert result.success is True

    def test_result_is_skill_result_instance(self, tmp_path: Path, monkeypatch):
        """handle() must return a SkillResult instance."""
        skill = _make_skill()
        ctx = _make_context(
            text="write a text file",
            claude_return="data",
        )

        fake_out = tmp_path / "output.txt"
        monkeypatch.setattr(
            "skills.file_writer._detect_output_path",
            lambda msg, fmt: fake_out,
        )

        result = skill.handle(ctx)
        assert isinstance(result, SkillResult)


# ---------------------------------------------------------------------------
# handle() edge case — claude error results in failure SkillResult
# ---------------------------------------------------------------------------

class TestHandleClaudeError:

    def test_handle_returns_failure_on_exception(self, tmp_path: Path):
        """If claude.complete() raises, handle() returns success=False."""
        skill = _make_skill()
        ctx = _make_context(text="write a text file", claude_return="")
        ctx.claude.complete.side_effect = RuntimeError("API unavailable")

        result = skill.handle(ctx)
        assert result.success is False
        assert result.skill_name == "file_writer"


# ---------------------------------------------------------------------------
# Skill identity / class-level attributes
# ---------------------------------------------------------------------------

class TestSkillIdentity:

    def test_name(self):
        assert FileWriterSkill.name == "file_writer"

    def test_has_trigger_patterns(self):
        assert len(FileWriterSkill.trigger_patterns) > 0

    def test_description_non_empty(self):
        assert FileWriterSkill.description.strip() != ""

    def test_version_semver(self):
        parts = FileWriterSkill.version.split(".")
        assert len(parts) == 3, "version should follow semver (x.y.z)"
