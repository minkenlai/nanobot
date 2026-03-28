"""Fallback provider: wraps multiple providers in a quota-aware chain.

On 429/quota errors the active slot advances to the next entry.
Resets to slot 0 at UTC midnight after the first fallback.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse


class FallbackProvider(LLMProvider):
    """Wraps multiple providers in a fallback chain.

    On 429/quota errors, advances to the next slot.
    Resets to slot 0 at UTC midnight after the first fallback.

    Args:
        slots: Ordered list of ``(provider, model_string)`` pairs.
               The first entry is the primary; subsequent entries are fallbacks.
    """

    def __init__(self, slots: list[tuple[LLMProvider, str]]) -> None:
        if not slots:
            raise ValueError("FallbackProvider requires at least one slot")
        # Don't call super().__init__() with api_key/api_base — we delegate to slots.
        self.api_key = None
        self.api_base = None
        self._slots = slots
        self._active_index = 0
        self._reset_at: datetime | None = None  # next UTC midnight (tz-aware) after first fallback
        # Inherit generation settings from the primary slot's provider.
        self.generation: GenerationSettings = slots[0][0].generation

    # ------------------------------------------------------------------
    # LLMProvider abstract method implementations
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Delegate to the active slot, falling back on quota errors."""
        notification = self._check_reset()

        while True:
            provider, slot_model = self._slots[self._active_index]
            # Always use the slot's own model string — FallbackProvider owns model
            # selection. The caller's `model` kwarg is intentionally ignored so that
            # sentinel strings (e.g. "fallbackModels") never leak to the API.
            try:
                response = await provider.chat(
                    messages=messages,
                    tools=tools,
                    model=slot_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                    tool_choice=tool_choice,
                )
                # Prepend any notification to the response content.
                if notification and response.content is not None:
                    response = LLMResponse(
                        content=notification + "\n\n" + response.content,
                        tool_calls=response.tool_calls,
                        finish_reason=response.finish_reason,
                        usage=response.usage,
                        reasoning_content=response.reasoning_content,
                        thinking_blocks=response.thinking_blocks,
                    )
                elif notification and response.content is None:
                    response = LLMResponse(
                        content=notification,
                        tool_calls=response.tool_calls,
                        finish_reason=response.finish_reason,
                        usage=response.usage,
                        reasoning_content=response.reasoning_content,
                        thinking_blocks=response.thinking_blocks,
                    )
                return response
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._is_quota_error(exc) and self._active_index < len(self._slots) - 1:
                    old_model = slot_model
                    self._active_index += 1
                    if self._reset_at is None:
                        self._reset_at = self._next_reset_midnight()
                    # Update generation settings to the new active slot's provider.
                    self.generation = self._slots[self._active_index][0].generation
                    new_model = self._slots[self._active_index][1]
                    fallback_msg = (
                        f"⚠️ Model quota hit on {old_model}. "
                        f"Switching to fallback: {new_model}."
                    )
                    notification = (
                        (notification + "\n" + fallback_msg) if notification else fallback_msg
                    )
                    # Retry with new slot (loop continues).
                else:
                    raise

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """Stream from the active slot, falling back on quota errors.

        If a fallback notification is pending, it is delivered as a leading
        delta before the actual response stream begins.
        """
        notification = self._check_reset()

        while True:
            provider, slot_model = self._slots[self._active_index]
            # Always use the slot's own model string — see chat() for rationale.
            try:
                # Deliver any pending notification as a leading delta.
                if notification and on_content_delta:
                    await on_content_delta(notification + "\n\n")
                    notification = None

                response = await provider.chat_stream(
                    messages=messages,
                    tools=tools,
                    model=slot_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                    tool_choice=tool_choice,
                    on_content_delta=on_content_delta,
                )
                return response
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._is_quota_error(exc) and self._active_index < len(self._slots) - 1:
                    old_model = slot_model
                    self._active_index += 1
                    if self._reset_at is None:
                        self._reset_at = self._next_reset_midnight()
                    # Update generation settings to the new active slot's provider.
                    self.generation = self._slots[self._active_index][0].generation
                    new_model = self._slots[self._active_index][1]
                    fallback_msg = (
                        f"⚠️ Model quota hit on {old_model}. "
                        f"Switching to fallback: {new_model}."
                    )
                    notification = (
                        (notification + "\n" + fallback_msg) if notification else fallback_msg
                    )
                    # Retry with new slot (loop continues).
                else:
                    raise

    def get_default_model(self) -> str:
        """Return the active slot's model string."""
        return self._slots[self._active_index][1]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def active_model(self) -> str:
        """The model string of the currently active slot."""
        return self._slots[self._active_index][1]

    @property
    def memory_provider(self) -> LLMProvider:
        """The last (cheapest/most stable) slot's provider, for memory consolidation."""
        return self._slots[-1][0]

    @property
    def memory_model(self) -> str:
        """The last slot's model string, for memory consolidation."""
        return self._slots[-1][1]

    def _check_reset(self) -> str | None:
        """Return a reset notification if the quota window has rolled over, else None."""
        if self._reset_at and datetime.now(timezone.utc) >= self._reset_at:
            self._active_index = 0
            self._reset_at = None
            # Restore generation settings to the primary slot.
            self.generation = self._slots[0][0].generation
            return (
                f"✅ Quota window reset. Switching back to primary: {self.active_model}."
            )
        return None

    @staticmethod
    def _next_reset_midnight() -> datetime:
        """Return the next UTC midnight as a timezone-aware datetime."""
        now = datetime.now(timezone.utc)
        tomorrow = now.date() + timedelta(days=1)
        return datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0, tzinfo=timezone.utc)

    @staticmethod
    def _is_quota_error(exc: Exception) -> bool:
        """Return True for 429 / quota / daily-limit errors."""
        msg = str(exc).lower()
        return any(
            k in msg
            for k in ["429", "402", "quota", "rate limit", "daily limit", "resource_exhausted", "payment required"]
        )
