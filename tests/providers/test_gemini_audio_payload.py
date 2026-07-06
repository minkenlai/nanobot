"""Unit tests for GeminiNativeClient._convert_messages — audio → inlineData conversion."""

from nanobot.providers.gemini_provider import GeminiNativeClient


def _make_client():
    """Return a GeminiNativeClient with a fake key (no network calls needed)."""
    return GeminiNativeClient(api_key="fake-key")


# ── Standard audio block (explicit mime_type + data) ──────────────────────────


def test_audio_block_with_all_fields():
    """Audio part with explicit mime_type and data → inlineData with both fields."""
    client = _make_client()

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "audio",
                    "mime_type": "audio/mpeg",
                    "data": "SGVsbG8gV29ybGQ=",  # base64 placeholder
                }
            ],
        }
    ]

    _sys_instr, contents = client._convert_messages(messages)

    assert _sys_instr is None
    assert len(contents) == 1
    assert contents[0]["role"] == "user"
    assert len(contents[0]["parts"]) == 1

    part = contents[0]["parts"][0]
    assert "inlineData" in part
    assert part["inlineData"]["mimeType"] == "audio/mpeg"
    assert part["inlineData"]["data"] == "SGVsbG8gV29ybGQ="


# ── Missing optional fields ───────────────────────────────────────────────────


def test_audio_block_missing_mime_type_defaults_to_wav():
    """Audio part without mime_type → defaults to audio/wav."""
    client = _make_client()

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "audio",
                    "data": "c29tZV9hdWRpb19iYXNlNjQ=",
                }
            ],
        }
    ]

    _sys_instr, contents = client._convert_messages(messages)

    part = contents[0]["parts"][0]
    assert part["inlineData"]["mimeType"] == "audio/wav"
    assert part["inlineData"]["data"] == "c29tZV9hdWRpb19iYXNlNjQ="


def test_audio_block_missing_data_defaults_to_empty_string():
    """Audio part without data → defaults to empty string."""
    client = _make_client()

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "audio",
                    "mime_type": "audio/flac",
                }
            ],
        }
    ]

    _sys_instr, contents = client._convert_messages(messages)

    part = contents[0]["parts"][0]
    assert part["inlineData"]["mimeType"] == "audio/flac"
    assert part["inlineData"]["data"] == ""


def test_audio_block_missing_both_optional_fields():
    """Audio part with neither mime_type nor data → defaults applied."""
    client = _make_client()

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "audio",
                }
            ],
        }
    ]

    _sys_instr, contents = client._convert_messages(messages)

    part = contents[0]["parts"][0]
    assert part["inlineData"]["mimeType"] == "audio/wav"
    assert part["inlineData"]["data"] == ""


# ── Mixed content (text + audio) ──────────────────────────────────────────────


def test_mixed_text_and_audio_in_single_message():
    """User message with both text and audio parts → both parts in contents."""
    client = _make_client()

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Listen to this clip:"},
                {
                    "type": "audio",
                    "mime_type": "audio/ogg",
                    "data": "b2dnX2RhdGE=",
                },
            ],
        }
    ]

    _sys_instr, contents = client._convert_messages(messages)

    assert len(contents[0]["parts"]) == 2
    assert contents[0]["parts"][0] == {"text": "Listen to this clip:"}
    assert contents[0]["parts"][1] == {
        "inlineData": {
            "mimeType": "audio/ogg",
            "data": "b2dnX2RhdGE=",
        }
    }


# ── Audio across multiple messages (role merging) ─────────────────────────────


def test_audio_messages_are_merged_when_consecutive_same_role():
    """Two consecutive user messages with audio → merged into single content entry."""
    client = _make_client()

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "audio",
                    "mime_type": "audio/wav",
                    "data": "YXVkaW8x",
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "audio",
                    "mime_type": "audio/mp3",
                    "data": "YXVkaW8y",
                }
            ],
        },
    ]

    _sys_instr, contents = client._convert_messages(messages)

    # Should be merged into one "user" content with 2 parts
    assert len(contents) == 1
    assert contents[0]["role"] == "user"
    assert len(contents[0]["parts"]) == 2

    assert contents[0]["parts"][0] == {"inlineData": {"mimeType": "audio/wav", "data": "YXVkaW8x"}}
    assert contents[0]["parts"][1] == {"inlineData": {"mimeType": "audio/mp3", "data": "YXVkaW8y"}}


# ── Audio with system instruction present ─────────────────────────────────────


def test_audio_preserved_alongside_system_instruction():
    """System message + user audio message → both systemInstruction and contents populated."""
    client = _make_client()

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {
            "role": "user",
            "content": [{"type": "audio", "mime_type": "audio/wav", "data": "dGVzdA=="}],
        },
    ]

    sys_instr, contents = client._convert_messages(messages)

    assert sys_instr is not None
    assert sys_instr["parts"] == [{"text": "You are a helpful assistant."}]
    assert contents[0]["parts"][0]["inlineData"]["mimeType"] == "audio/wav"
    assert contents[0]["parts"][0]["inlineData"]["data"] == "dGVzdA=="
