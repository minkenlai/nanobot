"""Tests for metadata-driven session context injection in prompt assembly."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.agent.context import ContextBuilder, TranscriptInput
from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.session.metadata_store import SessionMetadataStore


def test_context_builder_prepends_session_context_after_system_prompt(tmp_path: Path) -> None:
    builder = ContextBuilder(tmp_path)
    transcript = TranscriptInput(
        history=[{"role": "user", "content": "previous message"}],
        current_message="hello agent",
    )

    # Without session_context
    msgs_without = builder.build_transcript(transcript)
    assert len(msgs_without) == 3
    assert msgs_without[0]["role"] == "system"
    assert msgs_without[1]["role"] == "user"
    assert msgs_without[1]["content"] == "previous message"

    # With session_context
    session_ctx_text = "[Session Context: Staff Group]\nPROTOCOL: Group Chat. Stay silent unless @mentioned."
    msgs_with = builder.build_transcript(transcript, session_context=session_ctx_text)
    assert len(msgs_with) == 4
    # messages[0] is base system prompt
    assert msgs_with[0]["role"] == "system"
    # messages[1] is prepended session context
    assert msgs_with[1]["role"] == "system"
    assert msgs_with[1]["content"] == session_ctx_text
    # messages[2] is beginning of chat history
    assert msgs_with[2]["role"] == "user"
    assert msgs_with[2]["content"] == "previous message"
    # messages[3] is current message
    assert msgs_with[3]["role"] == "user"
    assert msgs_with[3]["content"] == "hello agent"


@pytest.mark.asyncio
async def test_agent_loop_injects_metadata_context_by_chat_id(tmp_path: Path) -> None:
    meta_file = tmp_path / "sessions_metadata.json"
    store = SessionMetadataStore(meta_file)
    store.set(
        "-1004453403218",
        label="Staff Group",
        context_injection="PROTOCOL: Group Chat. Stay silent unless @mentioned.",
        personality_override="Technical, concise, operations-focused.",
    )

    bus = MessageBus()
    provider = SimpleNamespace(
        get_default_model=lambda: "dummy-model",
        supports_tools=lambda: False,
    )

    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        session_metadata_store=store,
    )

    # Intercept loop.runner.run call to inspect transcript_input and transcript_builder
    captured_messages: list[dict] = []

    async def fake_runner_run(spec):
        if spec.transcript_builder and spec.transcript_input:
            captured_messages.extend(spec.transcript_builder(spec.transcript_input))
        return SimpleNamespace(
            final_content="ok",
            messages=[],
            summary_checkpoint=None,
            provider_compaction_applied=False,
            stop_reason="stop",
            failure_error_kind=None,
            usage=None,
            round_usages=[],
        )

    loop.runner.run = fake_runner_run

    msg = InboundMessage(
        channel="telegram",
        chat_id="-1004453403218",
        sender_id="user_1",
        content="hello staff",
    )

    # Process turn
    await loop._dispatch(msg)

    assert len(captured_messages) >= 2
    # Verify session context is injected at index 1
    injected = captured_messages[1]
    assert injected["role"] == "system"
    assert "[Session Context: Staff Group]" in injected["content"]
    assert "PROTOCOL: Group Chat" in injected["content"]
    assert "Personality: Technical, concise, operations-focused." in injected["content"]
