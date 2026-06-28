from types import SimpleNamespace
from unittest.mock import patch

import pytest

from nanobot.providers.anthropic_provider import AnthropicClient
from nanobot.providers.base import LLMResponse
from nanobot.providers.gemini_provider import GeminiNativeClient
from nanobot.providers.openai_compat_provider import OpenAICompatClient


@pytest.mark.asyncio
async def test_openai_compat_model_used():
    """Verify OpenAICompatClient populates model_used."""
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        client = OpenAICompatClient(api_key="k", default_model="m")

        # Mock a response object that behaves like the OpenAI SDK
        mock_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="hello", tool_calls=None), finish_reason="stop"
                )
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model="actual-model-name",
        )

        with patch.object(
            client,
            "chat",
            return_value=LLMResponse(content="hello", model_used="actual-model-name"),
        ):
            # We actually want to test the _parse method directly to be sure
            res = OpenAICompatClient._parse(mock_response)
            assert res.model_used == "actual-model-name"


@pytest.mark.asyncio
async def test_anthropic_model_used():
    """Verify AnthropicClient populates model_used."""
    mock_response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="hello")],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        model="claude-3-5-sonnet",
    )
    res = AnthropicClient._parse_response(mock_response)
    assert res.model_used == "claude-3-5-sonnet"


@pytest.mark.asyncio
async def test_gemini_model_used():
    """Verify GeminiNativeClient populates model_used."""
    mock_data = {
        "candidates": [{"content": {"parts": [{"text": "hello"}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
        "model": "gemini-pro-1.5",
    }
    client = GeminiNativeClient(api_key="k")
    res = client._parse_response(mock_data)
    assert res.model_used == "gemini-pro-1.5"
