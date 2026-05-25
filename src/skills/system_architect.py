"""
skills/system_architect.py
--------------------------
Converts hardware/utility requests and system-design prompts into
executable Python scripts or structured diagram descriptions.
"""

from __future__ import annotations

from core.context import ConversationContext, SkillResult
from skills.base import SkillBase

_SYSTEM_PROMPT = """\
You are an expert systems architect and Python developer.
When given a request related to system design, infrastructure diagrams,
hardware utilities, or Python scripting, produce a complete, immediately
runnable Python script or a detailed Mermaid/ASCII system-diagram.

Guidelines:
- For script requests: include a `if __name__ == "__main__":` block.
- For diagram requests: use Mermaid syntax inside a fenced code block.
- Add concise inline comments explaining key decisions.
- Keep outputs self-contained (no external deps unless essential).
- After the code/diagram, add a short "## How to use" section.
"""


class SystemArchitectSkill(SkillBase):
    """Generates Python scripts and system-design diagrams on demand."""

    name = "system_architect"
    description = (
        "Converts hardware/utility requests into executable Python scripts "
        "or structured system-design artifacts."
    )
    version = "1.0.0"
    trigger_patterns = [
        "architect",
        "design system",
        r"draw.*diagram",
        "system design",
        "infrastructure",
        "component diagram",
        r"create.*script",
        "python script",
        "executable",
        "hardware",
        "utility script",
    ]

    def handle(self, context: ConversationContext) -> SkillResult:
        try:
            messages = [
                {"role": "user", "content": _SYSTEM_PROMPT},
                *context.history,
                {"role": "user", "content": context.message.text},
            ]
            artifact = context.claude.complete(messages)
            return SkillResult(
                text=artifact,
                skill_name=self.name,
                success=True,
                metadata={"artifact_type": "script_or_diagram"},
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_result(str(exc))
