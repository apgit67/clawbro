"""
skills/data_repurposer.py
-------------------------
Transforms one media or data type into another (CSV<->JSON,
Markdown<->HTML, plain text reformatting, etc.).
"""

from __future__ import annotations

from core.context import ConversationContext, SkillResult
from skills.base import SkillBase

_SYSTEM_PROMPT = """\
You are a data transformation specialist.

The user wants to convert content from one format to another.
Rules:
- Detect the source format from context (or the user's description).
- Produce ONLY the transformed output — no preamble, no commentary.
- Preserve all data fidelity; do not invent or drop fields.
- For CSV<->JSON: use standard encodings.
- For Markdown<->HTML: produce clean, semantic HTML or clean Markdown.
- If the source content is not provided inline, ask the user to paste it.

After the transformed output, add a one-line note:
> Transformed from <source_format> to <target_format>.
"""


class DataRepurposerSkill(SkillBase):
    """Transforms one data/media format into another using Claude."""

    name = "data_repurposer"
    description = (
        "Converts between data formats: CSV<->JSON, Markdown<->HTML, "
        "and other transformations."
    )
    version = "1.0.0"
    trigger_patterns = [
        "convert",
        "transform",
        "repurpose",
        r"from.*to",
        "change format",
        r"translate.*format",
        r"csv.*json",
        r"json.*csv",
        r"markdown.*html",
        r"html.*markdown",
    ]

    def handle(self, context: ConversationContext) -> SkillResult:
        try:
            messages = [
                {"role": "user", "content": _SYSTEM_PROMPT},
                *context.history,
                {"role": "user", "content": context.message.text},
            ]
            transformed = context.claude.complete(messages)
            return SkillResult(
                text=transformed,
                skill_name=self.name,
                success=True,
                metadata={"transformation": "text_based"},
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_result(str(exc))
