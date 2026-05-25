"""
skills/knowledge_synthesizer.py
--------------------------------
Processes raw data or local PDFs/files into polished technical documents.
"""

from __future__ import annotations

import os
import re

from core.context import ConversationContext, SkillResult
from skills.base import SkillBase

_SYSTEM_PROMPT = """\
You are a technical documentation specialist.
Transform the provided raw data, notes, or document excerpts into a
polished, well-structured technical document in Markdown format.

Use the following structure where applicable:
# Title
## Executive Summary
## Background / Context
## Key Findings / Analysis
## Recommendations
## References

Keep the language precise, professional, and free of filler words.
"""

# Regex to spot local filesystem paths in the user message
_PATH_RE = re.compile(
    r"""
    (?:^|(?<=\s))           # start of string or preceded by whitespace
    (                       # capture group
        (?:[A-Za-z]:[/\\]   # Windows drive letter
        | [/~]              # Unix absolute or home-relative
        )
        [^\s"'<>|?*]+       # rest of path (no whitespace)
    )
    """,
    re.VERBOSE,
)

_MAX_FILE_BYTES = 256 * 1024  # 256 KB safety cap


def _try_read_file(path: str) -> str | None:
    """Attempt to read a local file; return its contents or None on failure."""
    expanded = os.path.expanduser(path)
    if not os.path.isfile(expanded):
        return None
    try:
        size = os.path.getsize(expanded)
        if size > _MAX_FILE_BYTES:
            return f"[File too large to inline ({size} bytes): {expanded}]"
        with open(expanded, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


class KnowledgeSynthesizerSkill(SkillBase):
    """Synthesises raw data / local files into polished technical docs."""

    name = "knowledge_synthesizer"
    description = (
        "Processes raw data or local PDFs into polished technical documents "
        "using Claude."
    )
    version = "1.0.0"
    trigger_patterns = [
        "synthesize",
        r"process.*pdf",
        "technical document",
        r"from.*data",
        "raw data",
        "polished",
        "knowledge base",
        r"extract.*from",
    ]

    def handle(self, context: ConversationContext) -> SkillResult:
        try:
            user_text = context.message.text
            extra_context = ""

            # Try to read any local file paths mentioned in the message
            paths_found = _PATH_RE.findall(user_text)
            file_sections: list[str] = []
            for path in paths_found:
                content = _try_read_file(path)
                if content is not None:
                    file_sections.append(
                        f"### File: {path}\n\n```\n{content}\n```"
                    )
            if file_sections:
                extra_context = (
                    "\n\n---\nAttached file content:\n\n"
                    + "\n\n".join(file_sections)
                )

            messages = [
                {"role": "user", "content": _SYSTEM_PROMPT},
                *context.history,
                {
                    "role": "user",
                    "content": user_text + extra_context,
                },
            ]
            document = context.claude.complete(messages)
            return SkillResult(
                text=document,
                skill_name=self.name,
                success=True,
                metadata={
                    "files_read": paths_found,
                    "extra_context_injected": bool(file_sections),
                },
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_result(str(exc))
