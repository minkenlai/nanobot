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
        slots: Ordered list of ``(provider, model_string, identifier)`` pairs.
               The first entry is the primary; subsequent entries are fallbacks.
    """

    def __init__(self, slots: list[tuple[LLMProvider, str, str, str]]) -> None:
        if not slots:
            raise ValueError("FallbackProvider requires at least one slot")
        # Don't call super().__init__() with api_key/api_base — we delegate to slots.
        self.api_key = None
        self.api_base = None
        self._slots = slots
        self._active_index = 0
        self._slot_reset_timezones = [s[3] for s in slots]
        self._reset_at: datetime | None = None
        self._failed_slot_reset_times: dict[int, datetime] = {}
        # Inherit generation settings from the primary slot's provider.
        self.generation: GenerationSettings = slots[0][0].generation
        self.debug = slots[0][0].debug
        self.dump_dir = slots[0][0].dump_dir

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
        """Delegate to the active slot, falling back on quota or local connectivity errors."""
        notification = self._check_reset()
        current_max_tokens = max_tokens
        # effective_index tracks which slot to use for *this* request.
        # Quota advances update both effective_index and self._active_index (permanent).
        # Connectivity advances on local slots update only effective_index (request-scoped).
        effective_index = self._active_index

        while True:
            provider, slot_model, slot_id, _ = self._slots[effective_index]
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

                # Quota error → permanent slot advance (resets at midnight).
                if self._is_quota_error(exc):
                    if is_max_tokens_issue and current_max_tokens > 1024:
                        current_max_tokens //= 2
                        logger.warning(
                            f"FallbackProvider: Reducing max_tokens to {current_max_tokens} for {slot_id} ({slot_model})"
                        )
                        continue

                    if effective_index < len(self._slots) - 1:
                        # Only advance if another concurrent request hasn't already done so.
                        if self._slots[effective_index][1] == slot_model:
                            old_id = slot_id
                            effective_index += 1
                            self._active_index = effective_index  # permanent

                            failed_slot_tz = self._slot_reset_timezones[effective_index - 1]
                            self._failed_slot_reset_times[effective_index - 1] = (
                                self._next_reset_midnight(failed_slot_tz)
                            )
                            self._reset_at = (
                                min(self._failed_slot_reset_times.values())
                                if self._failed_slot_reset_times
                                else None
                            )
                            self.generation = self._slots[effective_index][0].generation
                            new_id = self._slots[effective_index][2]
                            fallback_msg = (
                                f"⚠️ Model quota hit on {old_id}. Switching to fallback: {new_id}."
                            )
                            notification = (
                                (notification + "\n" + fallback_msg)
                                if notification
                                else fallback_msg
                            )
                        continue

                # Connectivity/timeout error on a local slot → request-scoped advance.
                # self._active_index is NOT updated so the next request still tries the
                # local provider first (it may just have been temporarily slow).
                is_local_slot = getattr(getattr(provider, "_spec", None), "is_local", False)
                if (
                    is_local_slot
                    and self._is_connectivity_error(exc)
                    and effective_index < len(self._slots) - 1
                ):
                    new_id = self._slots[effective_index + 1][2]
                    logger.warning(
                        "FallbackProvider: {} unreachable, trying {} for this request: {!r}",
                        slot_id,
                        new_id,
                        exc,
                    )
                    effective_index += 1
                    fallback_msg = f"⚠️ {slot_id} unavailable. Using {new_id} for this request."
                    notification = (
                        (notification + "\n" + fallback_msg) if notification else fallback_msg
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
        """Stream from the active slot, falling back on quota or local connectivity errors."""
        notification = self._check_reset()
        current_max_tokens = max_tokens
        # See chat() for the effective_index vs self._active_index design.
        effective_index = self._active_index

        while True:
            provider, slot_model, slot_id, _ = self._slots[effective_index]
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

                # Quota error → permanent slot advance (resets at midnight).
                if self._is_quota_error(exc):
                    if is_max_tokens_issue and current_max_tokens > 1024:
                        current_max_tokens //= 2
                        logger.warning(
                            f"FallbackProvider (stream): Reducing max_tokens to {current_max_tokens} for {slot_id} ({slot_model})"
                        )
                        continue

                    if effective_index < len(self._slots) - 1:
                        # Only advance if another concurrent request hasn't already done so.
                        if self._slots[effective_index][1] == slot_model:
                            old_id = slot_id
                            effective_index += 1
                            self._active_index = effective_index  # permanent

                            failed_slot_tz = self._slot_reset_timezones[effective_index - 1]
                            self._failed_slot_reset_times[effective_index - 1] = (
                                self._next_reset_midnight(failed_slot_tz)
                            )
                            self._reset_at = (
                                min(self._failed_slot_reset_times.values())
                                if self._failed_slot_reset_times
                                else None
                            )
                            self.generation = self._slots[effective_index][0].generation
                            new_id = self._slots[effective_index][2]
                            fallback_msg = (
                                f"⚠️ Model quota hit on {old_id}. Switching to fallback: {new_id}."
                            )
                            notification = (
                                (notification + "\n" + fallback_msg)
                                if notification
                                else fallback_msg
                            )
                        continue

                # Connectivity/timeout error on a local slot → request-scoped advance.
                is_local_slot = getattr(getattr(provider, "_spec", None), "is_local", False)
                if (
                    is_local_slot
                    and self._is_connectivity_error(exc)
                    and effective_index < len(self._slots) - 1
                ):
                    new_id = self._slots[effective_index + 1][2]
                    logger.warning(
                        "FallbackProvider: {} unreachable, trying {} for this request: {!r}",
                        slot_id,
                        new_id,
                        exc,
                    )
                    effective_index += 1
                    fallback_msg = f"⚠️ {slot_id} unavailable. Using {new_id} for this request."
                    notification = (
                        (notification + "\n" + fallback_msg) if notification else fallback_msg
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
    def active_identifier(self) -> str:
        """The config identifier of the currently active slot."""
        return self._slots[self._active_index][2]

    @property
    def fallback_identifiers(self) -> list[str]:
        """The config identifiers of all slots in the chain."""
        return [s[2] for s in self._slots]

    def _check_reset(self) -> str | None:
        """Return a reset notification if the quota window has rolled over, else None."""
        if self._reset_at and datetime.now(timezone.utc) >= self._reset_at:
            self._active_index = 0
            self._reset_at = None
            self._failed_slot_reset_times = {}  # Clear all failed slots on reset to primary
            # Restore generation settings to the primary slot.
            self.generation = self._slots[0][0].generation
            return f"✅ Quota window reset. Switching back to primary: {self.active_identifier}."
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

    @staticmethod
    def _is_connectivity_error(exc: Exception) -> bool:
        """Return True for timeout / connection-refused / network errors."""
        # Check the exception class name (catches httpx.ReadTimeout,
        # openai.APITimeoutError, openai.APIConnectionError, etc.)
        name = type(exc).__name__
        if "Timeout" in name or "Connection" in name or "Network" in name:
            return True
        msg = str(exc).lower()
        return "timeout" in msg or "timed out" in msg or "connection" in msg
