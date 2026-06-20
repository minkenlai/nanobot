"""Tests for audio block support in the provider layer (Task 2.1)."""

import base64

import pytest

from nanobot.providers.base import LLMClient, LLMResponse
from nanobot.utils.helpers import build_audio_content_block, has_audio_content

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_AUDIO_BYTES = b"\x00\x01\x02\x03\x04\x05"  # dummy audio payload
_SAMPLE_MIME = "audio/ogg"


def _make_audio_block(mime: str = _SAMPLE_MIME, path: str = "/tmp/voice.ogg") -> dict:
    return build_audio_content_block(_SAMPLE_AUDIO_BYTES, mime, path)


# ---------------------------------------------------------------------------
# build_audio_content_block
# ---------------------------------------------------------------------------


def test_build_audio_block_has_correct_type() -> None:
    block = build_audio_content_block(_SAMPLE_AUDIO_BYTES, _SAMPLE_MIME)
    assert block["type"] == "audio"


def test_build_audio_block_encodes_data_as_base64_data_uri() -> None:
    block = build_audio_content_block(_SAMPLE_AUDIO_BYTES, _SAMPLE_MIME)
    expected_b64 = base64.b64encode(_SAMPLE_AUDIO_BYTES).decode()
    assert block["data"] == f"data:{_SAMPLE_MIME};base64,{expected_b64}"


def test_build_audio_block_stores_mime_type() -> None:
    block = build_audio_content_block(_SAMPLE_AUDIO_BYTES, "audio/mp3")
    assert block["mime_type"] == "audio/mp3"


def test_build_audio_block_includes_meta_path() -> None:
    block = build_audio_content_block(_SAMPLE_AUDIO_BYTES, _SAMPLE_MIME, "/voice.ogg")
    assert block["_meta"]["path"] == "/voice.ogg"


def test_build_audio_block_omits_meta_when_path_empty() -> None:
    block = build_audio_content_block(_SAMPLE_AUDIO_BYTES, _SAMPLE_MIME, "")
    assert "_meta" not in block


# ---------------------------------------------------------------------------
# has_audio_content
# ---------------------------------------------------------------------------


def test_has_audio_content_detects_audio_block() -> None:
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "listen to this"},
                _make_audio_block(),
            ],
        },
    ]
    assert has_audio_content(msgs) is True


def test_has_audio_content_returns_false_for_text_only() -> None:
    msgs = [{"role": "user", "content": "hello world"}]
    assert has_audio_content(msgs) is False


def test_has_audio_content_returns_false_for_image_only() -> None:
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "look"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        },
    ]
    assert has_audio_content(msgs) is False


def test_has_audio_content_returns_false_for_empty_list() -> None:
    assert has_audio_content([]) is False


def test_has_audio_content_scans_multiple_messages() -> None:
    msgs = [
        {"role": "user", "content": "first message"},
        {"role": "assistant", "content": "ok"},
        {
            "role": "user",
            "content": [
                {"type": "audio", "data": "data:audio/ogg;base64,abc", "mime_type": "audio/ogg"},
            ],
        },
    ]
    assert has_audio_content(msgs) is True


# ---------------------------------------------------------------------------
# _sanitize_empty_content — audio blocks must survive
# ---------------------------------------------------------------------------


def test_sanitize_preserves_audio_blocks() -> None:
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "hi"},
                _make_audio_block(),
                {"type": "text", "text": ""},  # empty text — should be stripped
            ],
        },
    ]
    result = LLMClient._sanitize_empty_content(msgs)
    content = result[0]["content"]
    audio_blocks = [b for b in content if b.get("type") == "audio"]
    assert len(audio_blocks) == 1
    assert audio_blocks[0]["mime_type"] == _SAMPLE_MIME


def test_sanitize_preserves_audio_blocks_and_strips_meta() -> None:
    block = _make_audio_block()
    msgs = [{"role": "user", "content": [block]}]
    result = LLMClient._sanitize_empty_content(msgs)
    content = result[0]["content"]
    audio_block = [b for b in content if b.get("type") == "audio"][0]
    # _meta is always stripped by sanitize
    assert "_meta" not in audio_block
    assert audio_block["data"] == block["data"]


def test_sanitize_preserves_audio_when_text_becomes_empty() -> None:
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": ""},  # only empty text + audio
                _make_audio_block(),
            ],
        },
    ]
    result = LLMClient._sanitize_empty_content(msgs)
    content = result[0]["content"]
    # Empty text stripped, audio preserved
    assert len(content) == 1
    assert content[0]["type"] == "audio"


# ---------------------------------------------------------------------------
# _strip_audio_content
# ---------------------------------------------------------------------------


_AUDIO_MSG = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "listen to this"},
            {
                "type": "audio",
                "data": "data:audio/ogg;base64,dHVtcGdyYQ==",
                "mime_type": "audio/ogg",
                "_meta": {"path": "/tmp/voice.ogg"},
            },
        ],
    },
]


_AUDIO_MSG_NO_META = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "listen"},
            {
                "type": "audio",
                "data": "data:audio/mp3;base64,dHVtcGdyYQ==",
                "mime_type": "audio/mp3",
            },
        ],
    },
]


def test_strip_audio_replaces_with_text_placeholder() -> None:
    result = LLMClient._strip_audio_content(_AUDIO_MSG)
    assert result is not None
    content = result[0]["content"]
    audio_blocks = [b for b in content if b.get("type") == "audio"]
    assert len(audio_blocks) == 0
    placeholders = [b for b in content if b.get("type") == "text"]
    assert len(placeholders) == 2  # original text + audio placeholder
    assert any("[audio: /tmp/voice.ogg" in (b.get("text") or "") for b in placeholders)


def test_strip_audio_without_meta_uses_default_placeholder() -> None:
    result = LLMClient._strip_audio_content(_AUDIO_MSG_NO_META)
    assert result is not None
    content = result[0]["content"]
    placeholders = [b for b in content if b.get("type") == "text"]
    assert any("[audio omitted (audio/mp3)]" in (b.get("text") or "") for b in placeholders)


def test_strip_audio_returns_none_when_no_audio() -> None:
    result = LLMClient._strip_audio_content([{"role": "user", "content": "hello"}])
    assert result is None


def test_strip_audio_returns_none_for_image_only() -> None:
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        },
    ]
    result = LLMClient._strip_audio_content(msgs)
    assert result is None


def test_strip_audio_preserves_text_blocks() -> None:
    result = LLMClient._strip_audio_content(_AUDIO_MSG)
    content = result[0]["content"]
    text_blocks = [b for b in content if b.get("type") == "text"]
    assert any("listen to this" in (b.get("text") or "") for b in text_blocks)


# ---------------------------------------------------------------------------
# Retry integration — audio fallback (mirrors image fallback tests)
# ---------------------------------------------------------------------------


class ScriptedProvider(LLMClient):
    def __init__(self, responses):
        super().__init__()
        self._responses = list(responses)
        self.calls = 0
        self.last_kwargs: dict = {}

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
        self.last_kwargs = kwargs
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def get_default_model(self) -> str:
        return "test-model"


@pytest.mark.asyncio
async def test_non_transient_error_with_audio_retries_without_audio() -> None:
    """Any non-transient error retries once with audio stripped when audio is present."""
    provider = ScriptedProvider(
        [
            LLMResponse(content="API调用参数有误,请检查文档", finish_reason="error"),
            LLMResponse(content="ok, no audio"),
        ]
    )

    response = await provider.chat_with_retry(messages=_AUDIO_MSG)

    assert response.content == "ok, no audio"
    assert provider.calls == 2
    msgs_on_retry = provider.last_kwargs["messages"]
    for msg in msgs_on_retry:
        content = msg.get("content")
        if isinstance(content, list):
            assert all(b.get("type") != "audio" for b in content)
            assert any("[audio:" in (b.get("text") or "") for b in content)


@pytest.mark.asyncio
async def test_audio_fallback_returns_error_on_second_failure() -> None:
    """If the audio-stripped retry also fails, return that error."""
    provider = ScriptedProvider(
        [
            LLMResponse(content="model error", finish_reason="error"),
            LLMResponse(content="still failing", finish_reason="error"),
        ]
    )

    response = await provider.chat_with_retry(messages=_AUDIO_MSG)

    assert provider.calls == 2
    assert response.content == "still failing"
    assert response.finish_reason == "error"


@pytest.mark.asyncio
async def test_image_stripped_before_audio_on_non_transient_error() -> None:
    """When both image and audio are present, image stripping takes priority."""
    mixed_msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "mixed content"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,abc"},
                    "_meta": {"path": "/media/test.png"},
                },
                {
                    "type": "audio",
                    "data": "data:audio/ogg;base64,xyz",
                    "mime_type": "audio/ogg",
                },
            ],
        },
    ]

    provider = ScriptedProvider(
        [
            LLMResponse(content="bad request", finish_reason="error"),
            LLMResponse(content="ok"),
        ]
    )

    response = await provider.chat_with_retry(messages=mixed_msgs)

    assert response.content == "ok"
    assert provider.calls == 2
    msgs_on_retry = provider.last_kwargs["messages"]
    for msg in msgs_on_retry:
        content = msg.get("content")
        if isinstance(content, list):
            # Image should be stripped (first priority)
            assert all(b.get("type") != "image_url" for b in content)
            # Audio placeholder should still be present (audio not stripped)
            assert any("[image:" in (b.get("text") or "") for b in content)
            assert any(b.get("type") == "audio" for b in content)


@pytest.mark.asyncio
async def test_stream_retry_strips_audio_on_non_transient_error() -> None:
    """chat_stream_with_retry also strips audio on non-transient errors."""
    provider = ScriptedProvider(
        [
            LLMResponse(content="bad request", finish_reason="error"),
            LLMResponse(content="ok"),
        ]
    )

    response = await provider.chat_stream_with_retry(messages=_AUDIO_MSG)

    assert response.content == "ok"
    assert provider.calls == 2
    msgs_on_retry = provider.last_kwargs["messages"]
    for msg in msgs_on_retry:
        content = msg.get("content")
        if isinstance(content, list):
            assert all(b.get("type") != "audio" for b in content)
