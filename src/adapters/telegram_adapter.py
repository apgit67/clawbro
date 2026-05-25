"""
adapters/telegram_adapter.py
-----------------------------
Optional Telegram bot adapter for ClawBro.

Uses python-telegram-bot (AsyncIO API, v21+).
Only starts if TELEGRAM_BOT_TOKEN is set in the environment.

Auth: TELEGRAM_ALLOWED_USER_IDS (comma-separated integers) is an allowlist.
Only users in that list may interact. The bot fails closed — if the list is
unset or empty, every message is rejected.
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


def _parse_allowed_ids(env_val: str) -> set[int]:
    """Parse TELEGRAM_ALLOWED_USER_IDS into a set of ints. Returns empty set if not set."""
    if not env_val:
        return set()
    ids: set[int] = set()
    for part in env_val.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


class TelegramAdapter:
    """
    Telegram bot adapter. Forwards messages to the SkillRouter and replies
    with the SkillResult text.

    Parameters
    ----------
    router:
        Initialised SkillRouter.
    memory_factory:
        Callable(session_id: str) -> MemoryStore. Called once per chat_id to
        create a per-chat memory store.
    claude:
        Shared ClaudeClient instance.
    token:
        Telegram bot token. If None, reads TELEGRAM_BOT_TOKEN from env.
    allowed_user_ids:
        Allowlist of Telegram user IDs permitted to interact with the bot.
        Reads from TELEGRAM_ALLOWED_USER_IDS env var if not provided. If empty,
        the bot fails closed and rejects all users.
    """

    def __init__(
        self,
        router: "SkillRouter",
        memory_factory,
        claude: "ClaudeClient",
        token: str | None = None,
        allowed_user_ids: set[int] | None = None,
    ) -> None:
        self._router = router
        self._memory_factory = memory_factory
        self._claude = claude
        self._token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._allowed_ids = allowed_user_ids if allowed_user_ids is not None else \
            _parse_allowed_ids(os.environ.get("TELEGRAM_ALLOWED_USER_IDS", ""))
        # Per-chat memory stores: chat_id -> MemoryStore
        self._memories: dict[int, "MemoryStore"] = {}

    def is_configured(self) -> bool:
        """Return True if TELEGRAM_BOT_TOKEN is set."""
        return bool(self._token)

    def run(self) -> None:
        """
        Start the Telegram bot. Blocks until interrupted.
        Raises ImportError if python-telegram-bot is not installed.
        Raises RuntimeError if TELEGRAM_BOT_TOKEN is not set.
        """
        if not self._token:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN is not set. "
                "Export it in your environment or .env file to enable the Telegram adapter."
            )

        try:
            from telegram import Update  # type: ignore[import]
            from telegram.ext import (  # type: ignore[import]
                Application,
                ContextTypes,
                MessageHandler,
                filters,
            )
        except ImportError as exc:
            raise ImportError(
                "python-telegram-bot is required for the Telegram adapter. "
                "Install it with: pip install python-telegram-bot>=21.0"
            ) from exc

        import asyncio

        app = Application.builder().token(self._token).build()

        async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            if update.message is None or update.message.text is None:
                return

            user = update.effective_user
            chat_id = update.effective_chat.id if update.effective_chat else 0
            user_id = user.id if user else 0
            username = user.username or str(user_id) if user else "unknown"

            # Auth check — fail closed: with no allowlist configured, reject
            # everyone rather than letting any Telegram user drive the bot.
            if not self._allowed_ids or user_id not in self._allowed_ids:
                logger.warning(
                    "Rejected message from unauthorized user %s (%d)", username, user_id
                )
                await update.message.reply_text(
                    "Sorry, you are not authorized to use this bot."
                )
                return

            text = update.message.text.strip()
            logger.info("Telegram message from %s: %r", username, text[:80])

            # Per-chat memory store (keyed by chat_id)
            if chat_id not in self._memories:
                import uuid
                self._memories[chat_id] = self._memory_factory(str(uuid.uuid4()))

            memory = self._memories[chat_id]
            session_id = memory.session_id

            from core.context import ConversationContext, InputMessage

            msg = InputMessage(
                text=text,
                source="telegram",
                user_id=str(user_id),
                session_id=session_id,
                timestamp=time.time(),
                metadata={
                    "chat_id": chat_id,
                    "message_id": update.message.message_id,
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

            # Dispatch and reply
            result = self._router.dispatch(msg, context)
            reply = result.text if result.success else f"Error: {result.error_message or result.text}"
            memory.add_turn("assistant", result.text)

            # Telegram message limit is 4096 chars; split if needed
            for chunk in _split_message(reply, max_len=4096):
                await update.message.reply_text(chunk)

        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logger.info("Starting Telegram bot...")
        app.run_polling(allowed_updates=["message"])

    def stop(self) -> None:
        """Graceful stop (no-op; the polling loop handles signals)."""
        pass


def _split_message(text: str, max_len: int = 4096) -> list[str]:
    """Split a long message into chunks that fit within Telegram's limit."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:max_len])
        text = text[max_len:]
    return chunks
