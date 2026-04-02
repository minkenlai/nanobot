"""Fallback provider: wraps multiple providers in a quota-aware chain.

On 429/quota errors the active slot advances to the next entry.
Resets to slot 0 at UTC midnight after the first fallback.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse


class FallbackProvider(LLMProvider):
    """Wraps multiple providers in a fallback chain.

    On 429/quota errors, advances to the next slot.
    Resets to slot 0 at UTC midnight after the first fallback.

    Args:
        slots: Ordered list of ``(provider, model_string)`` pairs.
               The first entry is the primary; subsequent entries are fallbacks.
    """

    def __init__(self, slots: list[tuple[LLMProvider, str]], reset_timezone: str = "UTC") -> None:
        if not slots:
            raise ValueError("FallbackProvider requires at least one slot")
        # Don't call super().__init__() with api_key/api_base — we delegate to slots.
        self.api_key = None
        self.api_base = None
        self._slots = slots
        self._active_index = 0
        self._reset_at: datetime | None = (
            None  # next midnight in reset_timezone after first fallback
        )
        self._reset_timezone = reset_timezone
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
        temperature: float = 1.0,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Delegate to the active slot, falling back on quota errors."""
        notification = self._check_reset()
        current_max_tokens = max_tokens

        while True:
            provider, slot_model = self._slots[self._active_index]
            try:
                response = await provider.chat(
                    messages=messages,
                    tools=tools,
                    model=slot_model,
                    max_tokens=current_max_tokens,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                    tool_choice=tool_choice,
                )
                # Success - return response.
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
                msg = str(exc).lower()
                is_max_tokens_issue = "max_tokens" in msg or "max tokens" in msg

                # If we hit a 402/quota error, try next slot or reduce max_tokens
                if self._is_quota_error(exc):
                    if is_max_tokens_issue and current_max_tokens > 1024:
                        # Optimization: if we hit a max_tokens issue, try again with reduced tokens
                        # BEFORE giving up on the current slot or moving to next.
                        current_max_tokens //= 2
                        logger.warning(
                            f"FallbackProvider: Reducing max_tokens to {current_max_tokens} for {slot_model}"
                        )
                        continue

                    if self._active_index < len(self._slots) - 1:
                        # Only advance if another concurrent request hasn't already advanced it.
                        if self._slots[self._active_index][1] == slot_model:
                            old_model = slot_model
                            self._active_index += 1
                            if self._reset_at is None:
                                self._reset_at = self._next_reset_midnight(self._reset_timezone)
                            # Update generation settings to the new active slot's provider.
                            self.generation = self._slots[self._active_index][0].generation
                            new_model = self._slots[self._active_index][1]
                            fallback_msg = (
                                f"⚠️ Model quota hit on {old_model}. "
                                f"Switching to fallback: {new_model}."
                            )
                            notification = (
                                (notification + "\n" + fallback_msg)
                                if notification
                                else fallback_msg
                            )
                        continue
                raise

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """Stream from the active slot, falling back on quota errors."""
        notification = self._check_reset()
        current_max_tokens = max_tokens

        while True:
            provider, slot_model = self._slots[self._active_index]
            try:
                # Deliver any pending notification as a leading delta.
                if notification and on_content_delta:
                    await on_content_delta(notification + "\n\n")
                    notification = None

                response = await provider.chat_stream(
                    messages=messages,
                    tools=tools,
                    model=slot_model,
                    max_tokens=current_max_tokens,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                    tool_choice=tool_choice,
                    on_content_delta=on_content_delta,
                )
                return response
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                msg = str(exc).lower()
                is_max_tokens_issue = "max_tokens" in msg or "max tokens" in msg

                # If we hit a 402/quota error, try next slot or reduce max_tokens
                if self._is_quota_error(exc):
                    if is_max_tokens_issue and current_max_tokens > 1024:
                        # Optimization: if we hit a max_tokens issue, try again with reduced tokens
                        # BEFORE giving up on the current slot or moving to next.
                        current_max_tokens //= 2
                        logger.warning(
                            f"FallbackProvider (stream): Reducing max_tokens to {current_max_tokens} for {slot_model}"
                        )
                        continue

                    if self._active_index < len(self._slots) - 1:
                        # Only advance if another concurrent request hasn't already advanced it.
                        if self._slots[self._active_index][1] == slot_model:
                            old_model = slot_model
                            self._active_index += 1
                            if self._reset_at is None:
                                self._reset_at = self._next_reset_midnight(self._reset_timezone)
                            # Update generation settings to the new active slot's provider.
                            self.generation = self._slots[self._active_index][0].generation
                            new_model = self._slots[self._active_index][1]
                            fallback_msg = (
                                f"⚠️ Model quota hit on {old_model}. "
                                f"Switching to fallback: {new_model}."
                            )
                            notification = (
                                (notification + "\n" + fallback_msg)
                                if notification
                                else fallback_msg
                            )
                        continue
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
            return f"✅ Quota window reset. Switching back to primary: {self.active_model}."
        return None

    @staticmethod
    def _next_reset_midnight(tz_name: str = "UTC") -> datetime:
        """Return the next midnight in the given timezone as a timezone-aware UTC datetime."""
        from zoneinfo import ZoneInfo

        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            logger.warning(f"Invalid reset_timezone '{tz_name}', falling back to UTC")
            tz = timezone.utc

        now_tz = datetime.now(tz)
        tomorrow_tz = now_tz.date() + timedelta(days=1)
        # Create midnight in local zone
        midnight_tz = datetime(
            tomorrow_tz.year, tomorrow_tz.month, tomorrow_tz.day, 0, 0, 0, tzinfo=tz
        )
        # Convert back to UTC for internal storage
        return midnight_tz.astimezone(timezone.utc)

    @staticmethod
    def _is_quota_error(exc: Exception) -> bool:
        """Return True for 429 / quota / daily-limit errors."""
        msg = str(exc).lower()
        return any(
            k in msg
            for k in [
                "429",
                "402",
                "quota",
                "rate limit",
                "daily limit",
                "resource_exhausted",
                "payment required",
            ]
        )
