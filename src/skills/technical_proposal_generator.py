"""
skills/technical_proposal_generator.py
---------------------------------------
Drafts project Statements of Work (SOW) and technical blueprints.
"""

from __future__ import annotations

from core.context import ConversationContext, SkillResult
from skills.base import SkillBase

_SYSTEM_PROMPT = """\
You are a senior technical proposal writer with deep expertise in software
engineering and project management.

Produce a structured technical proposal / Statement of Work (SOW) with the
following mandatory sections:

## 1. Overview
Brief description of the project and its purpose.

## 2. Objectives
Bullet-list of SMART goals.

## 3. Scope
What is included and explicitly what is out-of-scope.

## 4. Tech Stack
Recommended technologies with brief justification.

## 5. Timeline
Phased milestone plan (use a Markdown table with Phase, Deliverable, Duration).

## 6. Risks & Mitigations
Top 3–5 risks with likelihood, impact, and mitigation strategy.

Use professional, concise language.  Fill in reasonable assumptions where
project details are not supplied.
"""


class TechnicalProposalGeneratorSkill(SkillBase):
    """Generates structured SOWs and technical blueprints via Claude."""

    name = "technical_proposal_generator"
    description = (
        "Drafts project Statements of Work or technical blueprints based on "
        "project constraints."
    )
    version = "1.0.0"
    trigger_patterns = [
        "proposal",
        "sow",
        "statement of work",
        "blueprint",
        "technical spec",
        "project brief",
        "scope",
        "requirements doc",
    ]

    def handle(self, context: ConversationContext) -> SkillResult:
        try:
            messages = [
                {"role": "user", "content": _SYSTEM_PROMPT},
                *context.history,
                {"role": "user", "content": context.message.text},
            ]
            proposal = context.claude.complete(messages)
            return SkillResult(
                text=proposal,
                skill_name=self.name,
                success=True,
                metadata={"document_type": "sow_or_blueprint"},
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_result(str(exc))
