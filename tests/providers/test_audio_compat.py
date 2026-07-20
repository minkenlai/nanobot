"""Tests for native audio (input_audio) support in OpenAICompatClient."""

import base64
from unittest.mock import MagicMock

import pytest

from nanobot.providers.openai_compat_provider import OpenAICompatClient
from nanobot.providers.registry import ProviderSpec

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_RAW = b"\x00\x01\x02\x03\x04\x05"
_SAMPLE_B64 = base64.b64encode(_SAMPLE_RAW).decode()


def _make_internal_audio_block(
    mime: str = "audio/ogg",
    b64_data: str | None = None,
) -> dict:
    """Build an internal-format audio block (as produced by build_audio_content_block)."""
    data = b64_data or _SAMPLE_B64
    return {
        "type": "audio",
        "data": f"data:{mime};base64,{data}",
        "mime_type": mime,
    }


def _make_openai_spec(supports_native_audio: bool = True) -> ProviderSpec:
    return ProviderSpec(
        name="openai",
        keywords=("openai", "gpt"),
        env_key="OPENAI_API_KEY",
        display_name="OpenAI",
        backend="openai_compat",
        supports_native_audio=supports_native_audio,
    )


# ---------------------------------------------------------------------------
# _convert_audio_blocks_to_input_audio — unit tests
# ---------------------------------------------------------------------------


class TestConvertAudioBlocks:
    def test_audio_block_converted_to_input_audio(self):
        audio_block = _make_internal_audio_block("audio/ogg")
        messages = [{"role": "user", "content": [audio_block]}]

        result = OpenAICompatClient._convert_audio_blocks_to_input_audio(messages)

        content = result[0]["content"]
        assert len(content) == 1
        block = content[0]
        assert block["type"] == "input_audio"
        assert "input_audio" in block
        assert block["input_audio"]["data"] == _SAMPLE_B64
        assert block["input_audio"]["format"] == "ogg"

    def test_mixed_text_and_audio_blocks(self):
        audio_block = _make_internal_audio_block("audio/wav")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Listen to this:"},
                    audio_block,
                    {"type": "text", "text": "What do you hear?"},
                ],
            },
        ]

        result = OpenAICompatClient._convert_audio_blocks_to_input_audio(messages)
        content = result[0]["content"]

        assert len(content) == 3
        assert content[0] == {"type": "text", "text": "Listen to this:"}
        assert content[1]["type"] == "input_audio"
        assert content[1]["input_audio"]["format"] == "wav"
        assert content[2] == {"type": "text", "text": "What do you hear?"}

    def test_string_content_passed_through_untouched(self):
        messages = [{"role": "user", "content": "Hello, world"}]
        result = OpenAICompatClient._convert_audio_blocks_to_input_audio(messages)
        assert result[0]["content"] == "Hello, world"

    def test_no_audio_blocks_returns_unchanged_messages(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Just text"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                ],
            },
        ]
        result = OpenAICompatClient._convert_audio_blocks_to_input_audio(messages)
        assert len(result[0]["content"]) == 2
        assert result[0]["content"][0] == {"type": "text", "text": "Just text"}

    def test_mime_type_mp3_maps_to_mp3_format(self):
        audio_block = _make_internal_audio_block("audio/mp3")
        messages = [{"role": "user", "content": [audio_block]}]

        result = OpenAICompatClient._convert_audio_blocks_to_input_audio(messages)
        assert result[0]["content"][0]["input_audio"]["format"] == "mp3"

    def test_mime_type_flac_maps_to_flac_format(self):
        audio_block = _make_internal_audio_block("audio/flac")
        messages = [{"role": "user", "content": [audio_block]}]

        result = OpenAICompatClient._convert_audio_blocks_to_input_audio(messages)
        assert result[0]["content"][0]["input_audio"]["format"] == "flac"

    def test_unknown_mime_defaults_to_wav_format(self):
        audio_block = _make_internal_audio_block("audio/unknown")
        messages = [{"role": "user", "content": [audio_block]}]

        result = OpenAICompatClient._convert_audio_blocks_to_input_audio(messages)
        assert result[0]["content"][0]["input_audio"]["format"] == "wav"

    def test_data_uri_prefix_stripped(self):
        """Ensure 'data:<mime>;base64,' prefix is stripped from the data field."""
        audio_block = _make_internal_audio_block("audio/ogg")
        messages = [{"role": "user", "content": [audio_block]}]

        result = OpenAICompatClient._convert_audio_blocks_to_input_audio(messages)
        raw_data = result[0]["content"][0]["input_audio"]["data"]
        assert not raw_data.startswith("data:")
        assert raw_data == _SAMPLE_B64


# ---------------------------------------------------------------------------
# _build_kwargs — integration tests (with mocked API)
# ---------------------------------------------------------------------------


class TestBuildKwargsAudio:
    def test_build_kwargs_converts_audio_when_supported(self):
        spec = _make_openai_spec(supports_native_audio=True)
        client = OpenAICompatClient(api_key="test-key", spec=spec)

        audio_block = _make_internal_audio_block("audio/ogg")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe this"},
                    audio_block,
                ],
            },
        ]

        kwargs = client._build_kwargs(
            messages=messages,
            tools=None,
            model="gpt-4o-audio-preview",
            max_tokens=1024,
            temperature=0.7,
            reasoning_effort=None,
            tool_choice=None,
        )

        # Verify the messages contain input_audio block
        msg_content = kwargs["messages"][0]["content"]
        audio_blocks = [b for b in msg_content if b.get("type") == "input_audio"]
        assert len(audio_blocks) == 1
        assert audio_blocks[0]["input_audio"]["format"] == "ogg"
        # data: prefix should be stripped
        assert not audio_blocks[0]["input_audio"]["data"].startswith("data:")

    def test_build_kwargs_skips_conversion_when_not_supported(self):
        spec = _make_openai_spec(supports_native_audio=False)
        client = OpenAICompatClient(api_key="test-key", spec=spec)

        audio_block = _make_internal_audio_block("audio/ogg")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Hello"},
                    audio_block,
                ],
            },
        ]

        kwargs = client._build_kwargs(
            messages=messages,
            tools=None,
            model="some-model",
            max_tokens=1024,
            temperature=0.7,
            reasoning_effort=None,
            tool_choice=None,
        )

        # Without native audio support, audio blocks should NOT be converted
        msg_content = kwargs["messages"][0]["content"]
        audio_blocks = [b for b in msg_content if b.get("type") == "input_audio"]
        assert len(audio_blocks) == 0
        # Internal audio block type should remain
        internal_audio = [b for b in msg_content if b.get("type") == "audio"]
        assert len(internal_audio) == 1


# ---------------------------------------------------------------------------
# End-to-end mock test — chat() sends input_audio in the payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestChatWithAudioMock:
    async def test_chat_payload_contains_input_audio(self):
        """Verify chat() sends the correct input_audio payload to OpenAI."""
        spec = _make_openai_spec(supports_native_audio=True)

        captured_kwargs: dict = {}

        async def mock_create(**kwargs):
            captured_kwargs.update(kwargs)
            # Return a mocked response
            mock_resp = MagicMock()
            mock_resp.model_dump.return_value = {
                "id": "chatcmpl-test",
                "model": "gpt-4o-audio-preview",
                "choices": [
                    {
                        "index": 0,
                        "message": {"content": "I hear a bell ringing.", "role": "assistant"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 50, "completion_tokens": 8, "total_tokens": 58},
            }
            return mock_resp

        client = OpenAICompatClient(api_key="test-key", spec=spec)
        # Replace the underlying SDK client's chat.completions.create
        client._client.chat.completions.create = mock_create

        audio_block = _make_internal_audio_block("audio/wav")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What sound is this?"},
                    audio_block,
                ],
            },
        ]

        response = await client.chat(messages=messages, model="gpt-4o-audio-preview")

        # Verify response is correct
        assert response.content == "I hear a bell ringing."
        assert response.finish_reason == "stop"
        assert response.usage["total_tokens"] == 58

        # Verify the payload sent to OpenAI
        sent_messages = captured_kwargs.get("messages", [])
        assert len(sent_messages) == 1
        content_blocks = sent_messages[0]["content"]

        audio_blocks = [b for b in content_blocks if b.get("type") == "input_audio"]
        assert len(audio_blocks) == 1
        assert audio_blocks[0]["input_audio"]["format"] == "wav"
        assert audio_blocks[0]["input_audio"]["data"] == _SAMPLE_B64

    async def test_chat_stream_payload_contains_input_audio(self):
        """Verify chat_stream() sends the correct input_audio payload."""
        spec = _make_openai_spec(supports_native_audio=True)

        captured_kwargs: dict = {}

        async def mock_stream_iter():
            # First chunk with content
            chunk1 = MagicMock()
            chunk1.choices = [MagicMock(delta=MagicMock(content="Hello", tool_calls=None))]
            chunk1.usage = None
            yield chunk1

            # Final chunk with usage
            chunk2 = MagicMock()
            chunk2.choices = [
                MagicMock(
                    delta=MagicMock(content=None, tool_calls=None),
                    finish_reason="stop",
                )
            ]
            chunk2.usage = MagicMock(prompt_tokens=50, completion_tokens=3, total_tokens=53)
            yield chunk2

        async def mock_create(**kwargs):
            captured_kwargs.update(kwargs)
            return mock_stream_iter()

        client = OpenAICompatClient(api_key="test-key", spec=spec)
        client._client.chat.completions.create = mock_create

        audio_block = _make_internal_audio_block("audio/flac")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe"},
                    audio_block,
                ],
            },
        ]

        response = await client.chat_stream(messages=messages, model="gpt-4o-audio-preview")

        assert response.content == "Hello"
        sent_messages = captured_kwargs.get("messages", [])
        audio_blocks = [b for b in sent_messages[0]["content"] if b.get("type") == "input_audio"]
        assert len(audio_blocks) == 1
        assert audio_blocks[0]["input_audio"]["format"] == "flac"

    async def test_chat_string_content_still_works(self):
        """Ensure plain string content is unaffected by audio support."""
        spec = _make_openai_spec(supports_native_audio=True)

        captured_kwargs: dict = {}

        async def mock_create(**kwargs):
            captured_kwargs.update(kwargs)
            mock_resp = MagicMock()
            mock_resp.model_dump.return_value = {
                "id": "chatcmpl-test",
                "model": "gpt-4o",
                "choices": [
                    {
                        "index": 0,
                        "message": {"content": "Text response", "role": "assistant"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
            }
            return mock_resp

        client = OpenAICompatClient(api_key="test-key", spec=spec)
        client._client.chat.completions.create = mock_create

        response = await client.chat(messages=[{"role": "user", "content": "Just a plain string"}])

        assert response.content == "Text response"
        # Content should remain a string
        assert captured_kwargs["messages"][0]["content"] == "Just a plain string"


# ---------------------------------------------------------------------------
# ProviderSpec — capability flag
# ---------------------------------------------------------------------------


class TestProviderSpecAudioFlag:
    def test_openai_spec_has_native_audio(self):
        from nanobot.providers.registry import find_by_name

        spec = find_by_name("openai")
        assert spec is not None
        assert spec.supports_native_audio is True

    def test_generic_spec_defaults_to_false(self):
        spec = ProviderSpec(
            name="test",
            keywords=("test",),
            env_key="TEST_KEY",
        )
        assert spec.supports_native_audio is False

    def test_custom_spec_can_enable_audio(self):
        spec = ProviderSpec(
            name="custom_audio",
            keywords=("custom",),
            env_key="CUSTOM_KEY",
            supports_native_audio=True,
        )
        assert spec.supports_native_audio is True
