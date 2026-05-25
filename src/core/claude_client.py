"""
core/claude_client.py
---------------------
Wraps the Anthropic SDK. Always streams. Handles context truncation.
Emits TurnEvent objects (ChunkEvent, ThinkingEvent, ToolCallEvent, ToolResultEvent, DoneEvent).

Ollama fallback: uses `requests` to hit http://localhost:11434/api/generate with stream=True.
"""

from __future__ import annotations

import json
import logging
from typing import Generator

import anthropic

from core.context import (
    ChunkEvent,
    DoneEvent,
    ThinkingEvent,
    ToolCallEvent,
    TurnEvent,
)

logger = logging.getLogger(__name__)


class ClaudeClient:
    """
    Wraps the Anthropic Python SDK.
    Always uses streaming. Handles context truncation before each call.
    Emits TurnEvent objects through a generator interface.

    Skills call this class; they never import `anthropic` directly.
    """

    DEFAULT_MODEL: str = "claude-sonnet-4-6"
    MAX_TOKENS: int = 8096
    HISTORY_TOKEN_BUDGET: int = 8000

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        use_ollama: bool = False,
        ollama_model: str = "llama3",
        ollama_host: str = "http://localhost:11434",
        ollama_api_key: str = "",
    ) -> None:
        """
        Args:
            api_key: Anthropic API key. Sourced from ANTHROPIC_API_KEY env var.
            model: Claude model ID. Can be overridden per-call.
            use_ollama: If True, route calls to local Ollama instead of Claude.
            ollama_model: Ollama model name to use (e.g. "llama3").
            ollama_host: Base URL for the Ollama HTTP API.
            ollama_api_key: Optional API key for Ollama cloud-hosted models
                (e.g. glm-5.1:cloud). Sent as ``Authorization: Bearer <key>``.
                Sourced from OLLAMA_API_KEY env var. Not needed for local models.
        """
        self.model = model
        self.use_ollama = use_ollama
        self.ollama_model = ollama_model
        self.ollama_host = ollama_host.rstrip("/")
        self.ollama_api_key = ollama_api_key
        self._client = anthropic.Anthropic(api_key=api_key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    class _OllamaAuthError(Exception):
        """Raised by _stream_ollama when the server returns 401 or 403."""

    def stream(
        self,
        messages: list[dict],
        system: str = "",
        max_tokens: int = 2048,
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> Generator[TurnEvent, None, None]:
        """
        Stream a response from Claude (or Ollama if use_ollama=True).
        Yields TurnEvent objects.
        On completion yields a DoneEvent with full assembled text.

        If Ollama is enabled but returns a 401/403 auth error, the call
        falls back transparently to the Claude API.

        Args:
            messages: List of {"role": str, "content": str} dicts (conversation history
                      including the current user message at the end).
            system: System prompt string.
            max_tokens: Maximum tokens to generate.
            tools: Optional Anthropic tool spec dicts.
            model: Override model for this call only.

        Yields:
            TurnEvent subclass instances in emission order.
        """
        if self.use_ollama:
            try:
                yield from self._stream_ollama(messages, system, max_tokens)
                return
            except ClaudeClient._OllamaAuthError as exc:
                logger.warning(
                    "Ollama returned an auth error (%s) — falling back to Claude API.", exc
                )
                yield ChunkEvent(text="[Ollama unavailable, switching to Claude]\n")

        yield from self._stream_claude(messages, system, max_tokens, tools, model)

    def complete(
        self,
        messages: list[dict],
        system: str = "",
        max_tokens: int = 2048,
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> str:
        """
        Non-streaming call. Collects all chunks, returns full text string.
        Uses stream() internally.

        Args:
            messages: Conversation history including current user message.
            system: System prompt.
            max_tokens: Max tokens to generate.
            tools: Optional tool specs.
            model: Optional model override.

        Returns:
            Fully assembled response text string.
        """
        full_text = ""
        for event in self.stream(messages, system, max_tokens, tools, model):
            if isinstance(event, DoneEvent):
                full_text = event.full_text
                break
            elif isinstance(event, ChunkEvent):
                full_text += event.text
        return full_text

    def _truncate_tool_result(self, result: str, max_chars: int = 4000) -> str:
        """
        Truncate long tool results to prevent context overflow.

        Uses a head-2/3 + tail-1/3 strategy with an ellipsis marker in the middle.

        Args:
            result: Raw tool result string.
            max_chars: Maximum character length after truncation.

        Returns:
            Truncated string with "[...truncated...]" marker if needed.
        """
        if len(result) <= max_chars:
            return result
        head_chars = (max_chars * 2) // 3
        tail_chars = max_chars - head_chars - len("\n[...truncated...]\n")
        if tail_chars < 0:
            tail_chars = 0
        return result[:head_chars] + "\n[...truncated...]\n" + result[-tail_chars:] if tail_chars else result[:max_chars]

    # ------------------------------------------------------------------
    # Internal: Claude streaming
    # ------------------------------------------------------------------

    def _stream_claude(
        self,
        messages: list[dict],
        system: str,
        max_tokens: int,
        tools: list[dict] | None,
        model: str | None,
    ) -> Generator[TurnEvent, None, None]:
        """Stream from the Anthropic Claude API."""
        effective_model = model or self.model
        assembled_text = ""
        input_tokens = 0
        output_tokens = 0
        stop_reason = "end_turn"

        call_kwargs: dict = {
            "model": effective_model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            call_kwargs["system"] = system
        if tools:
            call_kwargs["tools"] = tools

        try:
            with self._client.messages.stream(**call_kwargs) as stream:
                for event in stream:
                    event_type = type(event).__name__

                    # Text delta
                    if event_type == "RawContentBlockDeltaEvent":
                        delta = event.delta
                        delta_type = type(delta).__name__
                        if delta_type == "TextDelta":
                            assembled_text += delta.text
                            yield ChunkEvent(text=delta.text)
                        elif delta_type == "ThinkingDelta":
                            yield ThinkingEvent(text=delta.thinking)

                    # Tool use block start
                    elif event_type == "RawContentBlockStartEvent":
                        block = event.content_block
                        block_type = type(block).__name__
                        if block_type == "ToolUseBlock":
                            yield ToolCallEvent(
                                tool_name=block.name,
                                tool_input={},
                                tool_use_id=block.id,
                            )

                    # Message-level metadata (usage, stop reason)
                    elif event_type == "RawMessageDeltaEvent":
                        if hasattr(event, "usage") and event.usage:
                            output_tokens = getattr(event.usage, "output_tokens", 0)
                        if hasattr(event, "delta") and hasattr(event.delta, "stop_reason"):
                            if event.delta.stop_reason:
                                stop_reason = event.delta.stop_reason

                    elif event_type == "RawMessageStartEvent":
                        if hasattr(event, "message") and hasattr(event.message, "usage"):
                            input_tokens = getattr(event.message.usage, "input_tokens", 0)

                # Finalize
                final_message = stream.get_final_message()
                if final_message:
                    if final_message.usage:
                        input_tokens = final_message.usage.input_tokens
                        output_tokens = final_message.usage.output_tokens
                    if final_message.stop_reason:
                        stop_reason = final_message.stop_reason
                    # Build assembled text from all content blocks
                    texts = []
                    for block in final_message.content:
                        if hasattr(block, "text"):
                            texts.append(block.text)
                    if texts:
                        assembled_text = "".join(texts)

        except anthropic.APIConnectionError as exc:
            logger.error("Claude API connection error: %s", exc)
            assembled_text = f"[Connection error: {exc}]"
        except anthropic.RateLimitError as exc:
            logger.error("Claude API rate limit: %s", exc)
            assembled_text = "[Rate limit reached. Please wait and try again.]"
        except anthropic.APIStatusError as exc:
            logger.error("Claude API status error %s: %s", exc.status_code, exc.message)
            assembled_text = f"[API error {exc.status_code}: {exc.message}]"

        yield DoneEvent(
            full_text=assembled_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=stop_reason,
        )

    # ------------------------------------------------------------------
    # Internal: Ollama fallback
    # ------------------------------------------------------------------

    # Base URL used for direct cloud API access when an API key is present.
    OLLAMA_CLOUD_HOST: str = "https://ollama.com"

    def _stream_ollama(
        self,
        messages: list[dict],
        system: str,
        max_tokens: int,
    ) -> Generator[TurnEvent, None, None]:
        """Stream from Ollama.

        Routing:
        - API key present → hits ``https://ollama.com/api/generate`` directly
          with ``Authorization: Bearer <key>``.  This is the correct path for
          cloud-hosted models (e.g. glm-5.1:cloud).
        - No API key → hits ``self.ollama_host`` (default localhost:11434) and
          relies on ``ollama signin`` session credentials stored locally.
        """
        try:
            import requests  # type: ignore[import]
        except ImportError:
            yield ChunkEvent(text="[Ollama fallback requires 'requests' package]")
            yield DoneEvent(full_text="[Ollama fallback requires 'requests' package]")
            return

        # Build a simple prompt by concatenating history
        prompt_parts = []
        if system:
            prompt_parts.append(f"System: {system}\n")
        for msg in messages:
            role = msg.get("role", "user").capitalize()
            content = msg.get("content", "")
            prompt_parts.append(f"{role}: {content}")
        prompt = "\n".join(prompt_parts)

        payload = {
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": True,
            # Disable thinking mode for reasoning models (e.g. qwen3.5).
            # When think=True (the default), these models output everything into
            # the "thinking" field and produce zero "response" tokens, causing
            # blank output. think=False routes all output to the "response" field.
            "think": False,
            "options": {"num_predict": max_tokens},
        }

        # Route: API key → Ollama cloud directly; no key → local server
        if self.ollama_api_key:
            base_url = self.OLLAMA_CLOUD_HOST
            headers: dict[str, str] = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.ollama_api_key}",
            }
        else:
            base_url = self.ollama_host
            headers = {"Content-Type": "application/json"}

        assembled_text = ""
        try:
            with requests.post(
                f"{base_url}/api/generate",
                json=payload,
                headers=headers,
                stream=True,
                timeout=120,
            ) as resp:
                # Auth failures (cloud-gated models, token required, etc.) are
                # raised as _OllamaAuthError so stream() can fall back to Claude.
                if resp.status_code in (401, 403):
                    if self.ollama_api_key:
                        # Hitting cloud directly with a key — key is wrong/expired
                        hint = (
                            "OLLAMA_API_KEY was rejected by ollama.com. "
                            "Verify the key at https://ollama.com/settings/keys "
                            "and update OLLAMA_API_KEY in your .env file."
                        )
                    else:
                        # Hitting local server without a key — model needs auth
                        hint = (
                            "This model requires authentication. Either run "
                            "'ollama signin' to use session credentials, or set "
                            "OLLAMA_API_KEY in your .env (generate at "
                            "https://ollama.com/settings/keys)."
                        )
                    raise ClaudeClient._OllamaAuthError(
                        f"HTTP {resp.status_code} {resp.reason}: {hint}"
                    )
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    token = data.get("response", "")
                    if token:
                        assembled_text += token
                        yield ChunkEvent(text=token)
                    if data.get("done"):
                        break
        except ClaudeClient._OllamaAuthError:
            raise  # propagate to stream() for Claude fallback
        except Exception as exc:
            logger.error("Ollama streaming error: %s", exc)
            assembled_text = f"[Ollama error: {exc}]"
            yield ChunkEvent(text=assembled_text)

        yield DoneEvent(full_text=assembled_text)
