import pytest

from nanobot.providers.gemini_provider import GeminiNativeProvider


@pytest.mark.asyncio
async def test_gemini_usage_metadata_parsing():
    """Verify that Gemini usage metadata (camelCase) is correctly parsed."""
    provider = GeminiNativeProvider(api_key="fake")

    mock_data = {
        "candidates": [{"content": {"parts": [{"text": "Hello"}]}, "finishReason": "STOP"}],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 20,
            "totalTokenCount": 30,
        },
    }

    usage = provider._extract_usage(mock_data)
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 20
    assert usage["total_tokens"] == 30


@pytest.mark.asyncio
async def test_gemini_tool_config_generation():
    """Verify that OpenAI tool_choice is correctly converted to Gemini toolConfig."""
    provider = GeminiNativeProvider(api_key="fake")

    # Test 'required' (ANY)
    config = provider._convert_tool_choice("required")
    assert config == {"functionCallingConfig": {"mode": "ANY"}}

    # Test specific function
    tool_choice = {"type": "function", "function": {"name": "test_func"}}
    config = provider._convert_tool_choice(tool_choice)
    assert config == {
        "functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": ["test_func"]}
    }
