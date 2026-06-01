"""Tests for OpenAICompatClient shared semaphore behavior.

Validates that:
- Multiple client instances for the same provider share one semaphore.
- Different providers get separate semaphores.
- Providers without max_concurrent get no semaphore.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.providers.openai_compat_provider import OpenAICompatClient
from nanobot.providers.registry import ProviderSpec, find_by_name


def _fake_chat_response(content: str = "ok") -> SimpleNamespace:
    message = SimpleNamespace(
        content=content,
        tool_calls=None,
        reasoning_content=None,
    )
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


@pytest.fixture(autouse=True)
def _clear_semaphores():
    """Clear shared semaphores before and after each test."""
    OpenAICompatClient._semaphores.clear()
    yield
    OpenAICompatClient._semaphores.clear()


def test_same_provider_shares_semaphore():
    """Two clients for 'inferencia' must share the same semaphore instance."""
    spec = find_by_name("inferencia")
    assert spec is not None
    assert spec.max_concurrent == 1

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        client1 = OpenAICompatClient(
            api_key="key1",
            default_model="model1",
            spec=spec,
        )
        client2 = OpenAICompatClient(
            api_key="key2",
            default_model="model2",
            spec=spec,
        )

    assert client1._semaphore is not None
    assert client2._semaphore is not None
    assert client1._semaphore is client2._semaphore


def test_different_providers_have_separate_semaphores():
    """Clients for different providers must have separate semaphores."""
    spec_inferencia = find_by_name("inferencia")
    spec_ollama = find_by_name("ollama")
    assert spec_inferencia is not None
    assert spec_ollama is not None

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        client_inferencia = OpenAICompatClient(
            api_key="key1",
            default_model="model1",
            spec=spec_inferencia,
        )
        client_ollama = OpenAICompatClient(
            api_key="key2",
            default_model="model2",
            spec=spec_ollama,
        )

    assert client_inferencia._semaphore is not None
    assert client_ollama._semaphore is not None
    assert client_inferencia._semaphore is not client_ollama._semaphore


def test_no_spec_means_no_semaphore():
    """A client without a spec should have no semaphore."""
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        client = OpenAICompatClient(
            api_key="key",
            default_model="model",
            spec=None,
        )

    assert client._semaphore is None


def test_zero_max_concurrent_means_no_semaphore():
    """A provider with max_concurrent=0 should have no semaphore."""
    spec = ProviderSpec(
        name="unlimited",
        keywords=("unlimited",),
        env_key="",
        max_concurrent=0,
    )

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        client = OpenAICompatClient(
            api_key="key",
            default_model="model",
            spec=spec,
        )

    assert client._semaphore is None


@pytest.mark.asyncio
async def test_concurrent_requests_are_serialized():
    """Two concurrent chat calls on separate clients for the same provider
    must be serialized (only one in-flight at a time)."""
    spec = find_by_name("inferencia")
    assert spec is not None

    call_order: list[str] = []
    mock_create = AsyncMock()

    async def fake_create(**kwargs):
        name = kwargs.get("model", "unknown")
        call_order.append(f"start-{name}")
        await asyncio.sleep(0.05)
        call_order.append(f"end-{name}")
        return _fake_chat_response()

    mock_create.side_effect = fake_create

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as MockClient:
        client_instance = MockClient.return_value
        client_instance.chat.completions.create = mock_create

        client1 = OpenAICompatClient(
            api_key="key1",
            default_model="model1",
            spec=spec,
        )
        client2 = OpenAICompatClient(
            api_key="key2",
            default_model="model2",
            spec=spec,
        )

    # Fire both requests concurrently
    await asyncio.gather(
        client1.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="model1",
        ),
        client2.chat(
            messages=[{"role": "user", "content": "world"}],
            model="model2",
        ),
    )

    # With max_concurrent=1, requests must be serialized:
    # start-A, end-A, start-B, end-B (or vice versa)
    # NOT: start-A, start-B, end-A, end-B
    assert len(call_order) == 4
    # The first request must complete before the second starts
    assert call_order[0].startswith("start-")
    assert call_order[1].startswith("end-")
    assert call_order[2].startswith("start-")
    assert call_order[3].startswith("end-")
    # Both models should have been called
    models = {call.split("-")[1] for call in call_order}
    assert models == {"model1", "model2"}
