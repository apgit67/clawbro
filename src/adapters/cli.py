"""
adapters/cli.py
---------------
Interactive CLI adapter for ClawBro.

Uses `rich` for coloured output and live streaming display. Handles the
interactive REPL loop including all slash commands (/help, /memory,
/remember, /clear, /status, /quit, /exit).
"""

from __future__ import annotations

import logging
import sys
import time
from typing import TYPE_CHECKING

from rich.console import Console
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from core.context import ChunkEvent, ConversationContext, DoneEvent, InputMessage

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
except ImportError:  # prompt_toolkit is optional; fall back to Rich's input
    PromptSession = None  # type: ignore[assignment]
    InMemoryHistory = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from core.claude_client import ClaudeClient
    from core.router import SkillRouter
    from memory.store import MemoryStore

logger = logging.getLogger(__name__)

console = Console()

BANNER = r"""
   _____ _               ____
  / ____| |             |  _ \
 | |    | | __ ___      | |_) |_ __ ___
 | |    | |/ _` \ \ /\ / /  _ <| '__/ _ \
 | |____| | (_| |\ V  V /| |_) | | | (_) |
  \_____|_|\__,_| \_/\_/ |____/|_|  \___/
"""


class CLIAdapter:
    """
    Interactive command-line adapter that drives the skill router via
    a readline-style REPL.

    Parameters
    ----------
    router:
        Initialised SkillRouter with all skills registered.
    memory:
        MemoryStore for the current session.
    claude:
        ClaudeClient for streaming responses.
    session_id:
        UUID for this conversation session.
    user_id:
        Local username or "local" fallback.
    """

    def __init__(
        self,
        router: "SkillRouter",
        memory: "MemoryStore",
        claude: "ClaudeClient",
        session_id: str,
        user_id: str = "local",
    ) -> None:
        self._router = router
        self._memory = memory
        self._claude = claude
        self._session_id = session_id
        self._user_id = user_id
        # prompt_toolkit gives cross-platform cursor editing (arrow keys) and
        # up/down history. Falls back to Rich's console.input() if unavailable.
        self._prompt = (
            PromptSession(history=InMemoryHistory())
            if PromptSession is not None
            else None
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the interactive REPL. Blocks until the user quits."""
        console.print(BANNER, style="bold cyan", highlight=False)
        console.print(
            "Type a message or [bold]/help[/bold] for commands. "
            "[dim]/quit[/dim] to exit.\n"
        )

        while True:
            try:
                raw = self._read_input().strip()
            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Goodbye![/dim]")
                break

            if not raw:
                continue

            # Slash commands
            if raw.startswith("/"):
                should_exit = self._handle_command(raw)
                if should_exit:
                    break
                continue

            # Normal message — route through skill pipeline
            self._handle_message(raw)

    def _read_input(self) -> str:
        """Read one line from the user.

        Prefers prompt_toolkit (arrow-key cursor editing + history); falls back
        to Rich's console.input() when prompt_toolkit isn't installed.
        """
        if self._prompt is not None:
            return self._prompt.prompt("You: ")
        return console.input("[bold cyan]You:[/bold cyan] ")

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    def _handle_command(self, raw: str) -> bool:
        """Process a slash command. Returns True if the user wants to exit."""
        parts = raw.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("/quit", "/exit"):
            console.print("[dim]Goodbye![/dim]")
            return True

        elif cmd == "/help":
            self._cmd_help()

        elif cmd == "/memory":
            self._cmd_memory()

        elif cmd == "/remember":
            if not arg:
                console.print("[yellow]Usage: /remember <text>[/yellow]")
            else:
                result = self._memory.learn(arg)
                console.print(f"[green]{escape(result)}[/green]")

        elif cmd == "/clear":
            self._memory.clear_session()
            console.print("[dim]Session memory cleared.[/dim]")

        elif cmd == "/status":
            self._cmd_status()

        else:
            console.print(
                f"[yellow]Unknown command: {escape(cmd)}. "
                "Type [bold]/help[/bold] for available commands.[/yellow]"
            )

        return False

    def _cmd_help(self) -> None:
        """Print a table of all registered skills and slash commands."""
        table = Table(title="ClawBro Skills", show_header=True, header_style="bold magenta")
        table.add_column("Skill", style="cyan", no_wrap=True)
        table.add_column("Description")
        table.add_column("Version", style="dim", no_wrap=True)

        for skill_meta in self._router.list_skills():
            table.add_row(
                skill_meta["name"],
                skill_meta["description"],
                skill_meta.get("version", "1.0.0"),
            )
        console.print(table)
        console.print()

        cmd_table = Table(title="Slash Commands", show_header=True, header_style="bold blue")
        cmd_table.add_column("Command", style="cyan", no_wrap=True)
        cmd_table.add_column("Description")
        commands = [
            ("/help", "Show this help message"),
            ("/memory", "List all long-term memory keys"),
            ("/remember <text>", "Save a fact to long-term memory"),
            ("/clear", "Clear session conversation history"),
            ("/status", "Health check: DB, Claude API, Ollama"),
            ("/quit or /exit", "Exit ClawBro"),
        ]
        for cmd, desc in commands:
            cmd_table.add_row(cmd, desc)
        console.print(cmd_table)

    def _cmd_memory(self) -> None:
        """List all long-term memory keys."""
        keys = self._memory.list_keys()
        if not keys:
            console.print("[dim]No long-term memories stored yet.[/dim]")
            return

        table = Table(title="Long-Term Memory", show_header=True, header_style="bold green")
        table.add_column("Key", style="cyan")
        table.add_column("Value (preview)")
        for key in keys:
            results = self._memory.recall(key, limit=1)
            preview = ""
            if results:
                preview = results[0].get("value", "")[:80]
                if len(results[0].get("value", "")) > 80:
                    preview += "…"
            table.add_row(key, escape(preview))
        console.print(table)

    def _cmd_status(self) -> None:
        """Run a quick health check and display results."""
        console.print("[bold]ClawBro Status[/bold]")

        # DB check
        try:
            keys = self._memory.list_keys()
            console.print(f"  [green]✓[/green] Database: OK ({len(keys)} long-term memories)")
        except Exception as exc:  # noqa: BLE001
            console.print(f"  [red]✗[/red] Database: {exc}")

        # Claude check (a tiny no-op call)
        try:
            t0 = time.time()
            response = self._claude.complete(
                messages=[{"role": "user", "content": "ping"}],
                system="Reply with exactly: pong",
                max_tokens=10,
            )
            elapsed = time.time() - t0
            console.print(
                f"  [green]✓[/green] Claude API: connected "
                f"({self._claude.model}, {elapsed:.1f}s)"
            )
        except Exception as exc:  # noqa: BLE001
            console.print(f"  [red]✗[/red] Claude API: {exc}")

        # Ollama check
        if self._claude.use_ollama:
            try:
                import requests  # type: ignore[import]
                r = requests.get(f"{self._claude.ollama_host}/api/tags", timeout=3)
                r.raise_for_status()
                key_note = (
                    " [green](API key set)[/green]"
                    if self._claude.ollama_api_key
                    else " [yellow](no API key — cloud models need OLLAMA_API_KEY)[/yellow]"
                )
                console.print(
                    f"  [green]✓[/green] Ollama: running "
                    f"({self._claude.ollama_model}){key_note}"
                )
            except Exception as exc:  # noqa: BLE001
                console.print(f"  [yellow]○[/yellow] Ollama: not reachable ({exc})")
        else:
            console.print("  [dim]○[/dim] Ollama: disabled (set OLLAMA_ENABLED=true to enable)")

    # ------------------------------------------------------------------
    # Message handler
    # ------------------------------------------------------------------

    def _handle_message(self, text: str) -> None:
        """Route a user message through the skill pipeline and display output."""
        msg = InputMessage(
            text=text,
            source="cli",
            user_id=self._user_id,
            session_id=self._session_id,
            timestamp=time.time(),
        )

        history = self._memory.get_history()
        self._memory.add_turn("user", text)

        context = ConversationContext(
            message=msg,
            history=history,
            memory=self._memory,
            claude=self._claude,
            skill_name="",
            confidence=0.0,
            session_id=self._session_id,
        )

        # Route to find the skill (we need the name before dispatch for display)
        skill, confidence = self._router.route(text)
        context.skill_name = skill.name
        context.confidence = confidence

        # Show which skill is handling this
        if skill.name != "fallback":
            console.print(f"[dim](using: {skill.name})[/dim]")

        # Stream the response if the skill supports it, otherwise call handle()
        # For maximum compatibility, we call dispatch() which calls handle().
        # Skills that want to stream do so internally via context.claude.stream().
        # We capture the final SkillResult and display it.
        console.print("[bold green]ClawBro:[/bold green] ", end="")

        result = self._router.dispatch(msg, context)

        if result.success:
            console.print(result.text)
            self._memory.add_turn("assistant", result.text)
        else:
            console.print(
                f"[red]Error[/red]: {escape(result.error_message or result.text)}"
            )

        console.print()

    # ------------------------------------------------------------------
    # Streaming display helper (used by skills that yield events directly)
    # ------------------------------------------------------------------

    def stream_and_display(self, events, label: str = "ClawBro") -> str:
        """
        Consume a TurnEvent generator and display chunks in real-time using
        rich Live. Returns the fully assembled text.

        Args:
            events: Generator yielding TurnEvent objects.
            label: Display label prefix.

        Returns:
            Full assembled response text.
        """
        assembled = ""

        console.print(f"[bold green]{escape(label)}:[/bold green] ", end="")

        with Live(console=console, refresh_per_second=20, transient=False) as live:
            display_text = Text()
            for event in events:
                if isinstance(event, ChunkEvent):
                    assembled += event.text
                    display_text.append(event.text)
                    live.update(display_text)
                elif isinstance(event, DoneEvent):
                    assembled = event.full_text
                    break

        if not assembled:
            console.print("[dim](no response)[/dim]")

        return assembled
