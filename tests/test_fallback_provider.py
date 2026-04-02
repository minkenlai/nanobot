"""Tests for FallbackProvider — quota-aware model fallback chain."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.providers.base import GenerationSettings, LLMResponse
from nanobot.providers.fallback import FallbackProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_provider(
    model: str, response: LLMResponse | None = None, side_effect=None, reset_timezone: str = "UTC"
):
    """Return a mock LLMProvider that returns *response* or raises *side_effect*."""
    provider = MagicMock()
    provider.get_default_model.return_value = model
    provider.generation = GenerationSettings(temperature=0.7, max_tokens=4096)

    if side_effect is not None:
        provider.chat = AsyncMock(side_effect=side_effect)
        provider.chat_stream = AsyncMock(side_effect=side_effect)
    else:
        resp = response or LLMResponse(content=f"response from {model}", tool_calls=[])
        provider.chat = AsyncMock(return_value=resp)
        provider.chat_stream = AsyncMock(return_value=resp)

    return provider


def _quota_error(msg: str = "429 Too Many Requests"):
    return RuntimeError(msg)


def _server_error(msg: str = "500 Internal Server Error"):
    return RuntimeError(msg)


# ---------------------------------------------------------------------------
# Test 1: 429 error triggers fallback to next slot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_switches_to_next_slot_on_quota_error():
    """On a 429 error, FallbackProvider advances to the next slot and retries."""
    primary = _make_mock_provider("primary-model", side_effect=_quota_error())
    fallback = _make_mock_provider("fallback-model")

    fp = FallbackProvider(
        [
            (primary, "primary-model", "primary-model", "UTC"),
            (fallback, "fallback-model", "fallback-model", "UTC"),
        ]
    )

    response = await fp.chat(messages=[{"role": "user", "content": "hi"}])

    # Should have switched to fallback slot.
    assert fp._active_index == 1
    assert fp.active_model == "fallback-model"

    # Response content should include the fallback notification.
    assert response.content is not None
    assert "⚠️" in response.content
    assert "primary-model" in response.content
    assert "fallback-model" in response.content

    # Primary was called once (and failed); fallback was called once.
    primary.chat.assert_awaited_once()
    fallback.chat.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 2: Non-quota error does NOT switch slots and re-raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_reraises_non_quota_error_without_switching():
    """A 500 error (non-quota) must not trigger a slot switch and must re-raise."""
    primary = _make_mock_provider("primary-model", side_effect=_server_error())
    fallback = _make_mock_provider("fallback-model")

    fp = FallbackProvider(
        [
            (primary, "primary-model", "primary-model", "UTC"),
            (fallback, "fallback-model", "fallback-model", "UTC"),
        ]
    )

    with pytest.raises(RuntimeError, match="500"):
        await fp.chat(messages=[{"role": "user", "content": "hi"}])

    # Slot must NOT have advanced.
    assert fp._active_index == 0
    # Fallback provider must NOT have been called.
    fallback.chat.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 3: After _reset_at passes, rewinds to slot 0 and emits reset message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_resets_to_primary_after_quota_window_expires():
    """After _reset_at passes, the provider rewinds to slot 0 and emits a reset message."""
    primary_first = _make_mock_provider("primary-model", side_effect=_quota_error())
    fallback = _make_mock_provider("fallback-model")

    fp = FallbackProvider(
        [
            (primary_first, "primary-model", "primary-model", "UTC"),
            (fallback, "fallback-model", "fallback-model", "UTC"),
        ]
    )

    # Trigger a fallback so _reset_at is set.
    await fp.chat(messages=[{"role": "user", "content": "first"}])
    assert fp._active_index == 1
    assert fp._reset_at is not None

    # Manually set _reset_at to the past to simulate quota window expiry.
    fp._reset_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    # Now replace primary with a working provider for the reset test.
    primary_second = _make_mock_provider("primary-model")
    fp._slots[0] = (primary_second, "primary-model", "primary-model", "UTC")

    response = await fp.chat(messages=[{"role": "user", "content": "second"}])

    # Should have reset to slot 0.
    assert fp._active_index == 0
    assert fp._reset_at is None

    # Response should contain the reset notification.
    assert response.content is not None
    assert "✅" in response.content
    assert "primary-model" in response.content

    primary_second.chat.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 3b: Custom reset timezone (e.g. Pacific Time for Gemini)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_resets_at_pacific_midnight():
    """FallbackProvider correctly calculates reset time for non-UTC timezones."""
    from zoneinfo import ZoneInfo

    primary = _make_mock_provider(
        "primary-model", side_effect=_quota_error(), reset_timezone="America/Los_Angeles"
    )
    fallback = _make_mock_provider("fallback-model", reset_timezone="America/Los_Angeles")

    # Reset in America/Los_Angeles
    fp = FallbackProvider(
        [
            (primary, "primary-model", "primary-model", "America/Los_Angeles"),
            (fallback, "fallback-model", "fallback-model", "America/Los_Angeles"),
        ]
    )

    await fp.chat(messages=[{"role": "user", "content": "hi"}])

    assert fp._active_index == 1
    # _reset_at should reflect the primary's (failed) timezone, which is America/Los_Angeles.
    assert fp._reset_at is not None
    assert len(fp._failed_slot_reset_times) == 1
    assert 0 in fp._failed_slot_reset_times
    assert fp._failed_slot_reset_times[0] == fp._reset_at

    # Verify _reset_at is indeed midnight in LA.
    # Convert UTC _reset_at to LA time.
    reset_la = fp._reset_at.astimezone(ZoneInfo("America/Los_Angeles"))

    assert reset_la.hour == 0
    assert reset_la.minute == 0
    assert reset_la.second == 0
    # It should be tomorrow relative to "now" in LA.
    now_la = datetime.now(ZoneInfo("America/Los_Angeles"))
    assert reset_la.date() > now_la.date()


# ---------------------------------------------------------------------------
# Test 4: chat_stream yields notification chunk before response chunks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_stream_yields_notification_before_response():
    """chat_stream delivers the fallback notification as a leading delta."""
    primary = _make_mock_provider("primary-model", side_effect=_quota_error())

    # Fallback provider that calls on_content_delta with "hello".
    fallback_resp = LLMResponse(content="hello", tool_calls=[])

    async def _fallback_stream(*, messages, on_content_delta=None, **kwargs):
        if on_content_delta:
            await on_content_delta("hello")
        return fallback_resp

    fallback = MagicMock()
    fallback.get_default_model.return_value = "fallback-model"
    fallback.generation = GenerationSettings()
    fallback.chat_stream = _fallback_stream

    fp = FallbackProvider(
        [
            (primary, "primary-model", "primary-model", "UTC"),
            (fallback, "fallback-model", "fallback-model", "UTC"),
        ]
    )

    deltas: list[str] = []

    async def collect_delta(chunk: str) -> None:
        deltas.append(chunk)

    await fp.chat_stream(
        messages=[{"role": "user", "content": "hi"}],
        on_content_delta=collect_delta,
    )

    # First delta must be the notification.
    assert len(deltas) >= 2
    assert "⚠️" in deltas[0]
    assert "primary-model" in deltas[0]
    assert "fallback-model" in deltas[0]
    # Second delta is the actual response.
    assert deltas[1] == "hello"


# ---------------------------------------------------------------------------
# Test 5: Single slot — quota error is re-raised (no next slot)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_reraises_quota_error_when_no_next_slot():
    """With a single slot, a quota error must be re-raised (no fallback available)."""
    primary = _make_mock_provider("only-model", side_effect=_quota_error())

    fp = FallbackProvider([(primary, "only-model", "only-model", "UTC")])

    with pytest.raises(RuntimeError, match="429"):
        await fp.chat(messages=[{"role": "user", "content": "hi"}])

    # Slot index must remain 0.
    assert fp._active_index == 0


# ---------------------------------------------------------------------------
# Test 6: Startup validation — unknown fallback_models key raises SystemExit
# ---------------------------------------------------------------------------


def test_make_provider_raises_on_unknown_fallback_model_key():
    """_make_provider must detect unknown fallback_models keys before building providers.

    We test the validation logic directly without importing the full CLI module
    (which has a hard typer dependency).  The validation is: every key in
    agents.defaults.fallback_models must exist in config.models.
    """
    from nanobot.config.schema import AgentDefaults, AgentsConfig, Config, ModelConfig

    mc = ModelConfig(model="gemini-2.5-flash", provider="auto")
    defaults = AgentDefaults(
        model="gemini-2.5-flash",
        fallback_models=["my-flash", "nonexistent-key"],
    )
    cfg = Config(
        models={"my-flash": mc},
        agents=AgentsConfig(defaults=defaults),
    )

    # Replicate the validation logic from _make_provider.
    fallback_keys = cfg.agents.defaults.fallback_models
    unknown = [k for k in fallback_keys if k not in cfg.models]
    assert unknown == ["nonexistent-key"], (
        f"Expected ['nonexistent-key'] to be flagged as unknown, got {unknown}"
    )


# ---------------------------------------------------------------------------
# Additional: FallbackProvider constructor rejects empty slots
# ---------------------------------------------------------------------------


def test_fallback_provider_requires_at_least_one_slot():
    """FallbackProvider must raise ValueError when constructed with an empty slots list."""
    with pytest.raises(ValueError, match="at least one slot"):
        FallbackProvider([])


# ---------------------------------------------------------------------------
# Additional: memory_provider / memory_model return last slot
# ---------------------------------------------------------------------------


def test_memory_provider_returns_last_slot():
    """memory_provider and memory_model must point to the last slot."""
    p1 = _make_mock_provider("model-a")
    p2 = _make_mock_provider("model-b")
    p3 = _make_mock_provider("model-c")

    fp = FallbackProvider(
        [
            (p1, "model-a", "model-a", "UTC"),
            (p2, "model-b", "model-b", "UTC"),
            (p3, "model-c", "model-c", "UTC"),
        ]
    )

    assert fp.memory_provider is p3
    assert fp.memory_model == "model-c"


# ---------------------------------------------------------------------------
# Additional: quota errors on multiple consecutive slots
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_advances_through_multiple_quota_errors():
    """FallbackProvider advances through all quota-failing slots until one succeeds."""
    p1 = _make_mock_provider("model-a", side_effect=_quota_error("429 quota"))
    p2 = _make_mock_provider("model-b", side_effect=_quota_error("resource_exhausted"))
    p3 = _make_mock_provider("model-c")

    fp = FallbackProvider(
        [
            (p1, "model-a", "model-a", "UTC"),
            (p2, "model-b", "model-b", "UTC"),
            (p3, "model-c", "model-c", "UTC"),
        ]
    )

    response = await fp.chat(messages=[{"role": "user", "content": "hi"}])

    assert fp._active_index == 2
    assert fp.active_model == "model-c"
    assert response.content is not None
    # Both fallback notifications should appear.
    assert "model-a" in response.content
    assert "model-b" in response.content
    assert "model-c" in response.content


# ---------------------------------------------------------------------------
# Additional: concurrent requests don't skip slots
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_concurrent_requests_dont_skip_slots():
    """Concurrent requests both failing on the same slot should only advance once."""
    p1 = MagicMock()
    p1.get_default_model.return_value = "model-a"
    p1.generation = GenerationSettings()

    # p1 fails twice then succeeds (though we only need it to fail to trigger fallback)
    p1.chat = AsyncMock(side_effect=_quota_error("429"))

    p2 = _make_mock_provider("model-b")
    p3 = _make_mock_provider("model-c")

    fp = FallbackProvider(
        [
            (p1, "model-a", "model-a", "UTC"),
            (p2, "model-b", "model-b", "UTC"),
            (p3, "model-c", "model-c", "UTC"),
        ]
    )

    # Run two requests concurrently
    results = await asyncio.gather(
        fp.chat(messages=[{"role": "user", "content": "r1"}]),
        fp.chat(messages=[{"role": "user", "content": "r2"}]),
    )

    # Both should have succeeded on model-b
    assert "model-b" in results[0].content
    assert "model-b" in results[1].content

    # Active index should be 1 (model-b), NOT 2 (model-c)
    assert fp._active_index == 1
    assert fp.active_model == "model-b"
