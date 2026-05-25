"""
adapters/discord_adapter.py
----------------------------
Optional Discord bot adapter for ClawBro.

Uses discord.py (v2.3+, AsyncIO API).
Only starts if DISCORD_BOT_TOKEN is set in the environment.

The bot responds in any guild channel or DM where it can see messages.
Messages starting with "!" are ignored (reserved for Discord bot commands
in other bots). All other messages are forwarded to the SkillRouter.
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.claude_client import ClaudeClient
    from core.router import SkillRouter
    from memory.store import MemoryStore

logger = logging.getLogger(__name__)

# Discord message character limit
_DISCORD_MAX_LEN = 2000


class DiscordAdapter:
    """
    Discord bot adapter.

    Parameters
    ----------
    router:
        Initialised SkillRouter.
    memory_factory:
        Callable(session_id: str) -> MemoryStore. Called once per channel_id
        to create a per-channel memory store.
    claude:
        Shared ClaudeClient instance.
    token:
        Discord bot token. If None, reads DISCORD_BOT_TOKEN from env.
    """

    def __init__(
        self,
        router: "SkillRouter",
        memory_factory,
        claude: "ClaudeClient",
        token: str | None = None,
    ) -> None:
        self._router = router
        self._memory_factory = memory_factory
        self._claude = claude
        self._token = token or os.environ.get("DISCORD_BOT_TOKEN", "")
        # Per-channel memory stores: channel_id -> MemoryStore
        self._memories: dict[int, "MemoryStore"] = {}

    def is_configured(self) -> bool:
        """Return True if DISCORD_BOT_TOKEN is set."""
        return bool(self._token)

    def run(self) -> None:
        """
        Start the Discord bot. Blocks until interrupted.
        Raises ImportError if discord.py is not installed.
        Raises RuntimeError if DISCORD_BOT_TOKEN is not set.
        """
        if not self._token:
            raise RuntimeError(
                "DISCORD_BOT_TOKEN is not set. "
                "Export it in your environment or .env file to enable the Discord adapter."
            )

        try:
            import discord  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "discord.py is required for the Discord adapter. "
                "Install it with: pip install discord.py>=2.3.0"
            ) from exc

        intents = discord.Intents.default()
        intents.message_content = True

        client = discord.Client(intents=intents)

        @client.event
        async def on_ready() -> None:
            logger.info("Discord bot logged in as %s (ID: %s)", client.user, client.user.id)  # type: ignore[union-attr]

        @client.event
        async def on_message(message: discord.Message) -> None:
            # Ignore messages from the bot itself
            if message.author == client.user:
                return

            # Ignore empty messages or command-style messages (e.g. !something)
            text = message.content.strip()
            if not text or text.startswith("!"):
                return

            channel_id = message.channel.id
            user_id = str(message.author.id)
            username = str(message.author)

            logger.info("Discord message from %s in channel %d: %r", username, channel_id, text[:80])

            # Per-channel memory store
            if channel_id not in self._memories:
                import uuid
                self._memories[channel_id] = self._memory_factory(str(uuid.uuid4()))

            memory = self._memories[channel_id]
            session_id = memory.session_id

            from core.context import ConversationContext, InputMessage

            msg = InputMessage(
                text=text,
                source="discord",
                user_id=user_id,
                session_id=session_id,
                timestamp=time.time(),
                metadata={
                    "channel_id": channel_id,
                    "guild_id": message.guild.id if message.guild else None,
                    "message_id": message.id,
                    "username": username,
                },
            )

            history = memory.get_history()
            memory.add_turn("user", text)

            context = ConversationContext(
                message=msg,
                history=history,
                memory=memory,
                claude=self._claude,
                skill_name="",
                confidence=0.0,
                session_id=session_id,
            )

            # Show typing indicator while processing
            async with message.channel.typing():
                result = self._router.dispatch(msg, context)

            reply = result.text if result.success else f"Error: {result.error_message or result.text}"
            memory.add_turn("assistant", result.text)

            # Send reply, splitting if needed
            for chunk in _split_message(reply, max_len=_DISCORD_MAX_LEN):
                await message.channel.send(chunk)

        logger.info("Starting Discord bot...")
        client.run(self._token, log_handler=None)


def _split_message(text: str, max_len: int = _DISCORD_MAX_LEN) -> list[str]:
    """Split a long message into chunks within Discord's character limit."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:max_len])
        text = text[max_len:]
    return chunks
