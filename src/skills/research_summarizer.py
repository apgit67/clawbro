"""
skills/research_summarizer.py
------------------------------
Uses Claude to research a topic and produce a comprehensive summary.
Optionally reads local files/directories if paths are mentioned.
"""

from __future__ import annotations

import glob
import os
import re

from core.context import ConversationContext, SkillResult
from skills.base import SkillBase

_SYSTEM_PROMPT = """\
You are an expert research analyst with broad knowledge across science,
technology, engineering, and business domains.

Produce a comprehensive, well-structured summary on the requested topic.

Structure:
## Overview
## Key Concepts
## Current State / Recent Developments
## Important Considerations / Caveats
## Further Reading (suggest 3–5 topics or sources, do not invent URLs)

Write in clear, professional prose.  Cite important distinctions and trade-offs.
"""

# Path detection — same as knowledge_synthesizer
_PATH_RE = re.compile(
    r"""
    (?:^|(?<=\s))
    (
        (?:[A-Za-z]:[/\\]
        | [/~]
        )
        [^\s"'<>|?*]+
    )
    """,
    re.VERBOSE,
)

_MAX_FILE_BYTES = 128 * 1024  # 128 KB per file
_MAX_FILES = 5
_SUPPORTED_EXTS = {".txt", ".md", ".py", ".json", ".yaml", ".yml", ".csv", ".rst"}


def _collect_local_context(message: str) -> str:
    """Scan for local paths in the message; read matching files."""
    paths_found = _PATH_RE.findall(message)
    if not paths_found:
        return ""

    sections: list[str] = []
    files_read = 0

    for raw_path in paths_found:
        expanded = os.path.expanduser(raw_path)

        # If it's a directory, glob for supported file types
        if os.path.isdir(expanded):
            for ext in _SUPPORTED_EXTS:
                for fp in glob.glob(os.path.join(expanded, f"**/*{ext}"), recursive=True):
                    if files_read >= _MAX_FILES:
                        break
                    content = _safe_read(fp)
                    if content:
                        sections.append(f"### {fp}\n```\n{content}\n```")
                        files_read += 1

        elif os.path.isfile(expanded):
            _, ext = os.path.splitext(expanded)
            if ext.lower() in _SUPPORTED_EXTS and files_read < _MAX_FILES:
                content = _safe_read(expanded)
                if content:
                    sections.append(f"### {expanded}\n```\n{content}\n```")
                    files_read += 1

    if not sections:
        return ""
    return "\n\n---\n**Local file context:**\n\n" + "\n\n".join(sections)


def _safe_read(path: str) -> str | None:
    try:
        size = os.path.getsize(path)
        if size > _MAX_FILE_BYTES:
            return f"[File too large to inline: {size} bytes]"
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


class ResearchSummarizerSkill(SkillBase):
    """Produces comprehensive research summaries, optionally using local files."""

    name = "research_summarizer"
    description = (
        "Uses Claude to reason about a topic and produce a structured summary. "
        "Can include content from local files if paths are mentioned."
    )
    version = "1.0.0"
    trigger_patterns = [
        "research",
        r"summarize.*topic",
        r"find.*information",
        r"search.*for",
        "look up",
        r"what.*is",
        "explain",
        "tell me about",
        "summarize",
    ]

    def handle(self, context: ConversationContext) -> SkillResult:
        try:
            user_text = context.message.text
            local_ctx = _collect_local_context(user_text)

            messages = [
                {"role": "user", "content": _SYSTEM_PROMPT},
                *context.history,
                {"role": "user", "content": user_text + local_ctx},
            ]
            summary = context.claude.complete(messages)
            return SkillResult(
                text=summary,
                skill_name=self.name,
                success=True,
                metadata={"local_context_included": bool(local_ctx)},
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_result(str(exc))
