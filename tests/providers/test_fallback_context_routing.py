"""Tests for FallbackClient context-aware routing (prompt_tokens → slot selection)."""

import pytest

from nanobot.providers.base import GenerationSettings, LLMClient, LLMResponse
from nanobot.providers.fallback import FallbackClient


class MockProvider(LLMClient):
    """Minimal LLMClient mock that records the prompt_tokens it received."""

    def __init__(self, name: str, context_max: int) -> None:
        super().__init__()
        self.name = name
        self.generation = GenerationSettings(
            context_max=context_max,
            max_tokens=4096,
        )
        self.last_prompt_tokens: int | None = None

    def get_default_model(self) -> str:
        return self.name

    async def chat(  # type: ignore[override]
        self,
        messages: list,
        tools: list | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        reasoning_effort: str | None = None,
        tool_choice: str | dict | None = None,
        prompt_tokens: int | None = None,
    ) -> LLMResponse:
        self.last_prompt_tokens = prompt_tokens
        return LLMResponse(
            content=f"Response from {self.name}",
            tool_calls=[],
            finish_reason="stop",
            usage={"prompt_tokens": prompt_tokens or 0, "completion_tokens": 10},
        )


# ------------------------------------------------------------------ #
#  Helpers
# ------------------------------------------------------------------ #


def _build_fallback(
    context_maxes: list[int] = [4000, 8000, 32000],
) -> tuple[FallbackClient, list[MockProvider]]:
    """Create a FallbackClient with N slots and return (client, [providers])."""
    providers = [MockProvider(name=f"Model-{cm}", context_max=cm) for cm in context_maxes]
    # Slots: (provider, model_string, identifier, reset_timezone)
    slots = [(p, p.name, f"id-{i}", "UTC") for i, p in enumerate(providers)]
    return FallbackClient(slots), providers


# ------------------------------------------------------------------ #
#  Tests
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_small_prompt_uses_first_slot() -> None:
    """prompt < Slot 0 context_max → Slot 0 is used."""
    fallback, providers = _build_fallback()
    resp = await fallback.chat(messages=[], prompt_tokens=2_000)
    assert "Model-4000" in resp.content
    assert providers[0].last_prompt_tokens == 2_000


@pytest.mark.asyncio
async def test_medium_prompt_skips_first_slot() -> None:
    """Slot 0 < prompt < Slot 1 context_max → Slot 1 is used."""
    fallback, providers = _build_fallback()
    resp = await fallback.chat(messages=[], prompt_tokens=6_000)
    assert "Model-8000" in resp.content
    # Slot 0 should NOT have been called (its provider's last_prompt_tokens unchanged)
    assert providers[0].last_prompt_tokens is None
    assert providers[1].last_prompt_tokens == 6_000


@pytest.mark.asyncio
async def test_large_prompt_skips_first_two_slots() -> None:
    """Slot 1 < prompt < Slot 2 context_max → Slot 2 is used."""
    fallback, providers = _build_fallback()
    resp = await fallback.chat(messages=[], prompt_tokens=20_000)
    assert "Model-32000" in resp.content
    assert providers[0].last_prompt_tokens is None
    assert providers[1].last_prompt_tokens is None
    assert providers[2].last_prompt_tokens == 20_000


@pytest.mark.asyncio
async def test_huge_prompt_exceeds_all_slots() -> None:
    """prompt > all context_maxes → still attempts last slot (with warning)."""
    fallback, providers = _build_fallback()
    # 40k > 32k max — the code logs a warning but still tries the last slot
    resp = await fallback.chat(messages=[], prompt_tokens=40_000)
    assert "Model-32000" in resp.content
    assert providers[2].last_prompt_tokens == 40_000


@pytest.mark.asyncio
async def test_no_prompt_tokens_no_routing() -> None:
    """When prompt_tokens is None, context-aware routing is bypassed."""
    fallback, providers = _build_fallback()
    resp = await fallback.chat(messages=[])  # no prompt_tokens
    # Should use the first (active) slot regardless of context size
    assert "Model-4000" in resp.content


@pytest.mark.asyncio
async def test_prompt_tokens_none_on_provider() -> None:
    """prompt_tokens is forwarded to the slot provider unchanged."""
    fallback, providers = _build_fallback()
    await fallback.chat(messages=[], prompt_tokens=5_000)
    assert providers[1].last_prompt_tokens == 5_000


@pytest.mark.asyncio
async def test_exact_boundary_uses_slot() -> None:
    """prompt == slot context_max → slot is NOT skipped (strict >)."""
    fallback, providers = _build_fallback()
    resp = await fallback.chat(messages=[], prompt_tokens=4_000)
    assert "Model-4000" in resp.content


@pytest.mark.asyncio
async def test_one_over_boundary_skips_slot() -> None:
    """prompt == slot context_max + 1 → slot IS skipped."""
    fallback, providers = _build_fallback()
    resp = await fallback.chat(messages=[], prompt_tokens=4_001)
    assert "Model-8000" in resp.content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
