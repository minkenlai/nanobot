"""Self-prompt recovery when model returns empty after tool calls."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _make_provider(responses: list[LLMResponse]) -> MagicMock:
    """Return a provider that yields LLMResponse objects sequentially."""
    provider = MagicMock()
    call_idx = [0]

    async def chat_with_retry(**kwargs):
        resp = responses[call_idx[0]]
        call_idx[0] += 1
        return resp

    provider.chat_with_retry = chat_with_retry
    return provider


def _make_tools() -> MagicMock:
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="tool result")
    return tools


@pytest.mark.asyncio
async def test_runner_injects_self_prompt_on_empty_after_tools():
    """If model returns empty content after tool calls (iteration>0), a nudge is injected and runner retries."""
    captured_messages: list[list] = []
    call_count = [0]

    provider = MagicMock()

    async def chat_with_retry(*, messages, **kwargs):
        call_count[0] += 1
        captured_messages.append(list(messages))
        if call_count[0] == 1:
            # First call: tool call with no text content
            return LLMResponse(
                content="",
                tool_calls=[ToolCallRequest(id="c1", name="list_dir", arguments={"path": "."})],
                usage={},
            )
        elif call_count[0] == 2:
            # Second call: empty response — triggers nudge injection
            return LLMResponse(content="", tool_calls=[], usage={})
        # Third call (after nudge): returns a real response
        return LLMResponse(content="task done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = _make_tools()

    runner = AgentRunner(provider)
    result = await runner.run(
        AgentRunSpec(
            initial_messages=[{"role": "user", "content": "do task"}],
            tools=tools,
            model="test",
            max_iterations=5,
        )
    )

    assert result.final_content == "task done"
    assert result.stop_reason == "completed"

    # Third call's messages should contain the nudge (injected after the empty second call)
    nudge_in_third = any(
        "summarize the tool results" in (m.get("content") or "").lower()
        for m in captured_messages[2]
        if m.get("role") == "user"
    )
    assert nudge_in_third, "Self-prompt nudge was not injected after empty response"


@pytest.mark.asyncio
async def test_runner_fallback_at_last_iteration():
    """If model returns empty at the last iteration, runner uses a fallback message instead of crashing."""
    provider = _make_provider(
        [
            # iteration 0: tool call, no content
            LLMResponse(
                content="",
                tool_calls=[ToolCallRequest(id="c1", name="list_dir", arguments={"path": "."})],
                usage={},
            ),
            # iteration 1 (last): empty again — should fallback
            LLMResponse(content="", tool_calls=[], usage={}),
        ]
    )
    tools = _make_tools()

    runner = AgentRunner(provider)
    result = await runner.run(
        AgentRunSpec(
            initial_messages=[{"role": "user", "content": "do task"}],
            tools=tools,
            model="test",
            max_iterations=2,
        )
    )

    assert result.stop_reason == "completed"
    assert "processed the tool results" in (result.final_content or "").lower()


@pytest.mark.asyncio
async def test_runner_no_nudge_when_content_is_not_empty():
    """Normal path: non-empty content after tool calls should NOT trigger nudge."""
    captured_messages: list[list] = []
    call_count = [0]

    provider = MagicMock()

    async def chat_with_retry(*, messages, **kwargs):
        call_count[0] += 1
        captured_messages.append(list(messages))
        if call_count[0] == 1:
            return LLMResponse(
                content="ok",
                tool_calls=[ToolCallRequest(id="c1", name="list_dir", arguments={"path": "."})],
                usage={},
            )
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = _make_tools()

    runner = AgentRunner(provider)
    result = await runner.run(
        AgentRunSpec(
            initial_messages=[{"role": "user", "content": "do task"}],
            tools=tools,
            model="test",
            max_iterations=5,
        )
    )

    assert result.final_content == "done"
    # No nudge should appear in second call
    nudge_in_second = any(
        "summarize the tool results" in (m.get("content") or "").lower()
        for m in captured_messages[1]
        if m.get("role") == "user"
    )
    assert not nudge_in_second, "Nudge should not be injected when content is non-empty"
