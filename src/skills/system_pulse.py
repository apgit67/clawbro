"""
skills/system_pulse.py
----------------------
Analyses local environment health (CPU, RAM, disk) and recent log activity.
Degrades gracefully when psutil is unavailable.
"""

from __future__ import annotations

import os
import subprocess
import time

from core.context import ConversationContext, SkillResult
from skills.base import SkillBase

# ---------------------------------------------------------------------------
# psutil — optional dependency
# ---------------------------------------------------------------------------
try:
    import psutil  # type: ignore[import]
    _PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None  # type: ignore[assignment]
    _PSUTIL_AVAILABLE = False

_LOG_PATHS = [
    os.path.expanduser("~/.clawbro/clawbro.log"),
    "/var/log/syslog",
    "/var/log/messages",
]
_LOG_TAIL_LINES = 20
_LOG_MAX_BYTES = 8192


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------

def _collect_via_psutil() -> dict:
    """Gather metrics using psutil."""
    cpu_pct = psutil.cpu_percent(interval=0.5)
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    boot_ts = psutil.boot_time()
    uptime_secs = time.time() - boot_ts
    uptime_str = _fmt_uptime(uptime_secs)
    return {
        "cpu_percent": cpu_pct,
        "ram_used_gb": vm.used / 1e9,
        "ram_total_gb": vm.total / 1e9,
        "ram_percent": vm.percent,
        "disk_used_gb": disk.used / 1e9,
        "disk_total_gb": disk.total / 1e9,
        "disk_percent": disk.percent,
        "uptime": uptime_str,
        "source": "psutil",
    }


def _run(cmd: list[str]) -> str:
    """Run a subprocess command; return stdout or empty string on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _collect_via_subprocess() -> dict:
    """Fallback metric collection using system utilities."""
    metrics: dict = {"source": "subprocess"}

    # CPU — try top/wmic depending on platform
    import platform
    if platform.system() == "Windows":
        out = _run(
            ["wmic", "cpu", "get", "LoadPercentage", "/value"]
        )
        for line in out.splitlines():
            if "LoadPercentage" in line:
                try:
                    metrics["cpu_percent"] = float(line.split("=")[1])
                except (IndexError, ValueError):
                    pass
    else:
        out = _run(["vmstat", "1", "2"])
        lines = out.splitlines()
        if len(lines) >= 4:
            try:
                idle = float(lines[-1].split()[14])
                metrics["cpu_percent"] = round(100.0 - idle, 1)
            except (IndexError, ValueError):
                pass

    # Memory — free (Linux/macOS) or systeminfo (Windows)
    if platform.system() == "Windows":
        raw = _run(["systeminfo"])
        for line in raw.splitlines():
            if "Available Physical Memory" in line:
                metrics["ram_note"] = line.strip()
                break
    else:
        out = _run(["free", "-h"])
        if out:
            metrics["ram_note"] = out

    # Disk — df
    df_out = _run(["df", "-h", "/"] if platform.system() != "Windows" else ["wmic", "logicaldisk", "get", "size,freespace,caption"])
    if df_out:
        metrics["disk_note"] = df_out

    return metrics


def _fmt_uptime(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m}m"


def _read_log_tail(path: str) -> str | None:
    expanded = os.path.expanduser(path)
    if not os.path.isfile(expanded):
        return None
    try:
        with open(expanded, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            start = max(0, size - _LOG_MAX_BYTES)
            fh.seek(start)
            raw = fh.read().decode("utf-8", errors="replace")
        lines = raw.splitlines()[-_LOG_TAIL_LINES:]
        return "\n".join(lines)
    except OSError:
        return None


def _build_report(metrics: dict, log_snippets: list[tuple[str, str]]) -> str:
    parts = ["# ClawBro System Pulse Report", ""]

    # Metric section
    if "cpu_percent" in metrics:
        parts.append(f"**CPU usage:** {metrics['cpu_percent']}%")
    if "ram_percent" in metrics:
        parts.append(
            f"**RAM usage:** {metrics['ram_used_gb']:.1f} GB / "
            f"{metrics['ram_total_gb']:.1f} GB ({metrics['ram_percent']}%)"
        )
    elif "ram_note" in metrics:
        parts.append(f"**RAM:** {metrics['ram_note']}")
    if "disk_percent" in metrics:
        parts.append(
            f"**Disk (/):** {metrics['disk_used_gb']:.1f} GB / "
            f"{metrics['disk_total_gb']:.1f} GB ({metrics['disk_percent']}%)"
        )
    elif "disk_note" in metrics:
        parts.append(f"**Disk:**\n```\n{metrics['disk_note']}\n```")
    if "uptime" in metrics:
        parts.append(f"**Uptime:** {metrics['uptime']}")

    parts += [
        "",
        f"_Metrics collected via {metrics.get('source', 'unknown')}._",
        "",
    ]

    # Log section
    if log_snippets:
        parts.append("## Recent Log Activity")
        for log_path, snippet in log_snippets:
            parts += [
                f"### {log_path}",
                "```",
                snippet,
                "```",
                "",
            ]
    else:
        parts.append("_No readable log files found at known paths._")

    return "\n".join(parts)


class SystemPulseSkill(SkillBase):
    """Reports local system health metrics and recent log activity."""

    name = "system_pulse"
    description = (
        "Analyses local environment health: CPU, RAM, disk, and recent logs."
    )
    version = "1.0.0"
    trigger_patterns = [
        r"system.*health",
        "pulse",
        "performance",
        "cpu",
        "memory usage",
        "disk space",
        r"log.*activity",
        r"system.*status",
        r"how.*system.*doing",
        "metrics",
    ]

    def handle(self, context: ConversationContext) -> SkillResult:  # noqa: ARG002
        try:
            if _PSUTIL_AVAILABLE:
                metrics = _collect_via_psutil()
            else:
                metrics = _collect_via_subprocess()
                metrics.setdefault(
                    "note",
                    "psutil not installed — metrics collected via subprocess.",
                )

            # Collect log snippets
            log_snippets: list[tuple[str, str]] = []
            for log_path in _LOG_PATHS:
                snippet = _read_log_tail(log_path)
                if snippet:
                    log_snippets.append((log_path, snippet))

            report = _build_report(metrics, log_snippets)
            return SkillResult(
                text=report,
                skill_name=self.name,
                success=True,
                metadata={
                    "psutil_available": _PSUTIL_AVAILABLE,
                    "logs_found": [p for p, _ in log_snippets],
                },
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_result(str(exc))
