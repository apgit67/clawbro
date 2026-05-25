#!/usr/bin/env python3
"""ClawBro - Personal AI Assistant CLI

Entry point. Loads configuration, runs health checks, initialises all
components, and starts the CLI adapter loop.

Usage:
    python src/main.py [--ollama] [--model MODEL]
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: ensure src/ is on the Python path when running as
# `python src/main.py` from the outputs/ directory.
# ---------------------------------------------------------------------------
_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# Now we can import project modules.
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

console = Console()

__version__ = "1.0.0"


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _configure_logging(log_path: str | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_path:
        resolved = Path(log_path).expanduser()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(str(resolved)))
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------

def _check_db(db_path: str) -> tuple[bool, str]:
    """Verify the SQLite DB is accessible (creates it if absent)."""
    try:
        from memory import init_db
        init_db(db_path)
        resolved = Path(db_path).expanduser()
        return True, str(resolved)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _check_claude(api_key: str, model: str) -> tuple[bool, str]:
    """Ping the Claude API with a tiny request to verify connectivity."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        # Minimal non-streaming call to check auth
        msg = client.messages.create(
            model=model,
            max_tokens=5,
            messages=[{"role": "user", "content": "ping"}],
        )
        return True, model
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _check_ollama(ollama_host: str, ollama_model: str) -> tuple[bool, str]:
    """Check whether a local Ollama instance is reachable."""
    try:
        import requests  # type: ignore[import]
        r = requests.get(f"{ollama_host.rstrip('/')}/api/tags", timeout=3)
        r.raise_for_status()
        return True, ollama_model
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _check_telegram() -> tuple[bool, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    return bool(token), token[:10] + "..." if token else ""


def _check_discord() -> tuple[bool, str]:
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    return bool(token), token[:10] + "..." if token else ""


# ---------------------------------------------------------------------------
# Banner / startup display
# ---------------------------------------------------------------------------

def _print_startup_banner(
    db_ok: bool, db_info: str,
    claude_ok: bool, claude_info: str,
    tg_ok: bool,
    dc_ok: bool,
    ollama_ok: bool, ollama_info: str,
    ollama_enabled: bool,
    ollama_api_key: str = "",
) -> None:
    title = f"  ClawBro v{__version__} starting  "
    console.print(f"\n╔{'═' * len(title)}╗")
    console.print(f"║{title}║")
    console.print(f"╚{'═' * len(title)}╝\n")

    tick = "[green]✓[/green]"
    cross = "[red]✗[/red]"
    circle = "[dim]○[/dim]"

    # Database
    if db_ok:
        console.print(f"{tick} Database: {db_info}")
    else:
        console.print(f"{cross} Database: {db_info}")

    # Claude API
    if claude_ok:
        console.print(f"{tick} Claude API: connected ({claude_info})")
    else:
        console.print(f"{cross} Claude API: {claude_info}")

    # Telegram
    if tg_ok:
        console.print(f"{tick} Telegram: configured")
    else:
        console.print(f"{circle} Telegram: not configured (set TELEGRAM_BOT_TOKEN to enable)")

    # Discord
    if dc_ok:
        console.print(f"{tick} Discord: configured")
    else:
        console.print(f"{circle} Discord: not configured (set DISCORD_BOT_TOKEN to enable)")

    # Ollama
    if ollama_enabled:
        if ollama_ok:
            key_status = " [green]🔑 key set[/green]" if ollama_api_key else " [yellow]⚠ no API key (cloud models need OLLAMA_API_KEY)[/yellow]"
            console.print(f"{tick} Ollama: running ({ollama_info}){key_status}")
        else:
            console.print(f"{circle} Ollama: not running (optional offline fallback)")
    else:
        console.print(f"{circle} Ollama: not running (optional offline fallback)")

    console.print()


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="clawbro",
        description="ClawBro — Personal AI Assistant CLI",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override Claude model (default: from CLAUDE_MODEL env or claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--adapter",
        choices=("cli", "telegram", "discord"),
        default="cli",
        help="Which entry point to run (default: cli)",
    )
    parser.add_argument(
        "--ollama",
        action="store_true",
        default=False,
        help="Use Ollama local LLM instead of Claude API",
    )
    parser.add_argument(
        "--ollama-model",
        default=None,
        dest="ollama_model",
        help="Ollama model name (default: from OLLAMA_MODEL env or llama3)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Path to SQLite database (default: ~/.clawbro/memory.db)",
    )
    parser.add_argument(
        "--no-health-check",
        action="store_true",
        default=False,
        dest="no_health_check",
        help="Skip the Claude API ping on startup (faster cold start)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # 1. Load .env
    load_dotenv()

    args = _parse_args()

    # Resolve configuration (env vars take precedence over hardcoded defaults)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    model = args.model or os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
    max_tokens = int(os.environ.get("CLAUDE_MAX_TOKENS", "2048"))
    db_path = args.db or os.environ.get("CLAWBRO_DB_PATH", "~/.clawbro/memory.db")
    log_path = os.environ.get("CLAWBRO_LOG_PATH", "~/.clawbro/clawbro.log")

    ollama_enabled = args.ollama or os.environ.get("OLLAMA_ENABLED", "false").lower() == "true"
    ollama_model = args.ollama_model or os.environ.get("OLLAMA_MODEL", "llama3")
    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    ollama_api_key = os.environ.get("OLLAMA_API_KEY", "")
    # Ollama sets OLLAMA_HOST as a bare bind address (e.g. "0.0.0.0:11434").
    # Ensure it is always a full HTTP URL with a connectable host.
    if not ollama_host.startswith("http"):
        ollama_host = f"http://{ollama_host}"
    # 0.0.0.0 is a bind address — replace with localhost for outbound connections.
    ollama_host = ollama_host.replace("0.0.0.0", "localhost")

    # 2. Validate ANTHROPIC_API_KEY (required unless using Ollama)
    if not api_key and not ollama_enabled:
        console.print(
            "[red]Error:[/red] ANTHROPIC_API_KEY is not set.\n"
            "  - Add it to your .env file: ANTHROPIC_API_KEY=sk-ant-...\n"
            "  - Or export it: export ANTHROPIC_API_KEY=sk-ant-...\n"
            "  - Or use Ollama offline mode: --ollama\n"
        )
        sys.exit(1)

    # Configure logging
    _configure_logging(log_path)

    # 3. Run health checks
    db_ok, db_info = _check_db(db_path)

    if not db_ok:
        console.print(f"[red]Fatal:[/red] Cannot initialise database: {db_info}")
        sys.exit(1)

    if not args.no_health_check and not ollama_enabled:
        claude_ok, claude_info = _check_claude(api_key, model)
    else:
        # Skip ping — assume connected
        claude_ok, claude_info = True, model

    tg_ok, _ = _check_telegram()
    dc_ok, _ = _check_discord()

    if ollama_enabled:
        ollama_ok, ollama_info = _check_ollama(ollama_host, ollama_model)
    else:
        ollama_ok, ollama_info = False, ""

    # 4. Print startup banner
    _print_startup_banner(
        db_ok, db_info,
        claude_ok, claude_info,
        tg_ok, dc_ok,
        ollama_ok, ollama_info,
        ollama_enabled,
        ollama_api_key=ollama_api_key,
    )

    if not claude_ok and not ollama_enabled:
        console.print(
            f"[red]Error:[/red] Cannot connect to Claude API: {claude_info}\n"
            "  Check your ANTHROPIC_API_KEY and network connection."
        )
        sys.exit(1)

    # 5. Init DB (already done in _check_db, but ensure MemoryStore can open it)
    from memory import MemoryStore

    # 6. Instantiate ClaudeClient
    from core.claude_client import ClaudeClient
    claude = ClaudeClient(
        api_key=api_key,
        model=model,
        use_ollama=ollama_enabled,
        ollama_model=ollama_model,
        ollama_host=ollama_host,
        ollama_api_key=ollama_api_key,
    )

    # 7. Memory: the CLI uses one session-scoped store; the bot adapters create
    #    one store per chat/channel via a factory.
    resolved_db = str(Path(db_path).expanduser())
    session_id = str(uuid.uuid4())

    def memory_factory(sid: str) -> "MemoryStore":
        return MemoryStore(session_id=sid, db_path=resolved_db)

    # 8. Instantiate all skills
    from skills import get_all_skills
    all_skills = get_all_skills()

    # 9. Instantiate FallbackSkill
    from skills.base import FallbackSkill
    fallback = FallbackSkill()

    # 10. Instantiate SkillRouter
    from core.router import SkillRouter
    router = SkillRouter(skills=all_skills, fallback=fallback)

    # 11. Start the selected adapter
    if args.adapter == "telegram":
        from adapters.telegram_adapter import TelegramAdapter
        adapter = TelegramAdapter(
            router=router,
            memory_factory=memory_factory,
            claude=claude,
        )
        if not adapter.is_configured():
            console.print(
                "[red]Error:[/red] TELEGRAM_BOT_TOKEN is not set.\n"
                "  Add it to your .env file to run the Telegram adapter."
            )
            sys.exit(1)
        console.print("[dim]Starting Telegram bot. Press Ctrl+C to stop.[/dim]\n")
        adapter.run()
        return

    if args.adapter == "discord":
        from adapters.discord_adapter import DiscordAdapter
        adapter = DiscordAdapter(
            router=router,
            memory_factory=memory_factory,
            claude=claude,
        )
        if not adapter.is_configured():
            console.print(
                "[red]Error:[/red] DISCORD_BOT_TOKEN is not set.\n"
                "  Add it to your .env file to run the Discord adapter."
            )
            sys.exit(1)
        console.print("[dim]Starting Discord bot. Press Ctrl+C to stop.[/dim]\n")
        adapter.run()
        return

    # Default: interactive CLI
    try:
        user_id = getpass.getuser()
    except Exception:  # noqa: BLE001
        user_id = "local"

    console.print("[dim]Ready. Type a message or /help for commands.[/dim]\n")

    memory = memory_factory(session_id)
    from adapters.cli import CLIAdapter
    cli = CLIAdapter(
        router=router,
        memory=memory,
        claude=claude,
        session_id=session_id,
        user_id=user_id,
    )
    cli.run()

    # Cleanup
    memory.close()


if __name__ == "__main__":
    main()
