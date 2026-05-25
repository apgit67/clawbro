"""
skills/sandbox_guard.py
-----------------------
Static-analysis dry-run guard: checks generated Python code for dangerous
patterns WITHOUT executing it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.context import ConversationContext, SkillResult
from skills.base import SkillBase

# ---------------------------------------------------------------------------
# Dangerous pattern definitions
# ---------------------------------------------------------------------------

@dataclass
class _DangerRule:
    pattern: re.Pattern[str]
    severity: str        # "CRITICAL" | "HIGH" | "MEDIUM"
    description: str


_DANGER_RULES: list[_DangerRule] = [
    _DangerRule(
        re.compile(r"\bos\.system\s*\(", re.IGNORECASE),
        "CRITICAL",
        "os.system() can execute arbitrary shell commands.",
    ),
    _DangerRule(
        re.compile(r"\bsubprocess\b.*shell\s*=\s*True", re.IGNORECASE | re.DOTALL),
        "CRITICAL",
        "subprocess with shell=True enables shell injection.",
    ),
    _DangerRule(
        re.compile(r"rm\s+-rf\s+/", re.IGNORECASE),
        "CRITICAL",
        "rm -rf / detected — would wipe root filesystem.",
    ),
    _DangerRule(
        re.compile(r"\bshutil\.rmtree\s*\(\s*['\"/]", re.IGNORECASE),
        "HIGH",
        "shutil.rmtree() on what appears to be a root/absolute path.",
    ),
    _DangerRule(
        re.compile(r"\beval\s*\(", re.IGNORECASE),
        "HIGH",
        "eval() can execute arbitrary code at runtime.",
    ),
    _DangerRule(
        re.compile(r"\bexec\s*\(", re.IGNORECASE),
        "HIGH",
        "exec() can execute arbitrary code at runtime.",
    ),
    _DangerRule(
        re.compile(r"__import__\s*\(", re.IGNORECASE),
        "MEDIUM",
        "__import__() may dynamically load unexpected modules.",
    ),
    _DangerRule(
        re.compile(r"\bpickle\.loads?\s*\(", re.IGNORECASE),
        "HIGH",
        "pickle.load/loads() deserialises arbitrary Python objects.",
    ),
    _DangerRule(
        re.compile(r"\bchmod\s+777\b", re.IGNORECASE),
        "MEDIUM",
        "chmod 777 makes files world-writable.",
    ),
    _DangerRule(
        re.compile(r"\bcurl\b.*\|\s*bash", re.IGNORECASE),
        "CRITICAL",
        "curl piped to bash — classic code injection vector.",
    ),
    _DangerRule(
        re.compile(r"\bwget\b.*\|\s*sh", re.IGNORECASE),
        "CRITICAL",
        "wget piped to sh — classic code injection vector.",
    ),
]

# System directories that should not be touched by generated scripts
_FORBIDDEN_PATH_RE = re.compile(
    r"""
    (?:^|['"\s(])           # start of token
    (
        /etc/|/bin/|/sbin/|/usr/bin/|/usr/sbin/
        |/lib/|/lib64/
        |/sys/|/proc/
        |C:\\Windows\\System32
        |C:\\Windows\\SysWOW64
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _extract_code(text: str) -> str:
    """
    Pull code out of Markdown fenced blocks if present;
    otherwise treat the whole message as code.
    """
    fence_re = re.compile(r"```(?:python)?\n?(.*?)```", re.DOTALL | re.IGNORECASE)
    blocks = fence_re.findall(text)
    return "\n".join(blocks) if blocks else text


@dataclass
class _Finding:
    severity: str
    description: str
    line_number: int
    snippet: str


def _analyse(code: str) -> list[_Finding]:
    findings: list[_Finding] = []
    lines = code.splitlines()

    for line_no, line in enumerate(lines, start=1):
        for rule in _DANGER_RULES:
            if rule.pattern.search(line):
                findings.append(
                    _Finding(
                        severity=rule.severity,
                        description=rule.description,
                        line_number=line_no,
                        snippet=line.strip()[:120],
                    )
                )

    # Forbidden path check (whole-file scan)
    for match in _FORBIDDEN_PATH_RE.finditer(code):
        # find approximate line number
        start = match.start()
        line_no = code[:start].count("\n") + 1
        findings.append(
            _Finding(
                severity="HIGH",
                description=f"Access to protected system path: {match.group(1)}",
                line_number=line_no,
                snippet=match.group(0).strip()[:120],
            )
        )

    return findings


def _build_report(code: str, findings: list[_Finding]) -> str:
    lines = ["# ClawBro Sandbox Safety Report", ""]

    if not findings:
        lines += [
            "**Status: SAFE** — No dangerous patterns detected.",
            "",
            "The script passed all static checks.  Review it manually before "
            "executing in a production environment.",
        ]
    else:
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
        findings.sort(key=lambda f: severity_order.get(f.severity, 99))

        critical = sum(1 for f in findings if f.severity == "CRITICAL")
        high = sum(1 for f in findings if f.severity == "HIGH")
        medium = sum(1 for f in findings if f.severity == "MEDIUM")

        verdict = "UNSAFE" if critical or high else "REVIEW RECOMMENDED"
        lines += [
            f"**Status: {verdict}**",
            "",
            f"Found {len(findings)} issue(s): "
            f"{critical} CRITICAL, {high} HIGH, {medium} MEDIUM",
            "",
            "## Findings",
            "",
        ]
        for i, f in enumerate(findings, start=1):
            lines += [
                f"### {i}. [{f.severity}] Line {f.line_number}",
                f"**Issue:** {f.description}",
                f"**Code:** `{f.snippet}`",
                "",
            ]

    lines += [
        "---",
        "_This is a static analysis only.  The code was NOT executed._",
    ]
    return "\n".join(lines)


class SandboxGuardSkill(SkillBase):
    """
    Dry-runs Python code via static analysis and returns a safety report.
    Never executes the code.
    """

    name = "sandbox_guard"
    description = (
        "Static-analysis safety checker: inspects Python code for dangerous "
        "patterns without executing it."
    )
    version = "1.0.0"
    trigger_patterns = [
        r"dry.?run",
        "sandbox",
        r"safe.*run",
        r"test.*script",
        r"check.*code",
        r"validate.*script",
        r"will this.*break",
        "safe to run",
    ]

    def handle(self, context: ConversationContext) -> SkillResult:
        try:
            code = _extract_code(context.message.text)
            findings = _analyse(code)
            report = _build_report(code, findings)

            is_safe = not any(
                f.severity in ("CRITICAL", "HIGH") for f in findings
            )
            return SkillResult(
                text=report,
                skill_name=self.name,
                success=True,
                metadata={
                    "is_safe": is_safe,
                    "finding_count": len(findings),
                    "severities": {
                        "critical": sum(
                            1 for f in findings if f.severity == "CRITICAL"
                        ),
                        "high": sum(
                            1 for f in findings if f.severity == "HIGH"
                        ),
                        "medium": sum(
                            1 for f in findings if f.severity == "MEDIUM"
                        ),
                    },
                },
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_result(str(exc))
