"""Tests for UpdateSessionMetadataTool."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.tools.session_metadata import UpdateSessionMetadataTool
from nanobot.session.metadata_store import SessionMetadataStore


@pytest.mark.asyncio
async def test_update_session_metadata_tool_crud(tmp_path: Path) -> None:
    meta_file = tmp_path / "sessions_metadata.json"
    store = SessionMetadataStore(meta_file)
    tool = UpdateSessionMetadataTool(store=store)

    assert tool.name == "update_session_metadata"

    # 1. List when empty
    res_list = await tool.execute(action="list")
    assert not res_list.is_error
    assert "No session metadata entries configured" in res_list

    # 2. Set
    res_set = await tool.execute(
        action="set",
        chat_id="-1004453403218",
        label="Staff Group",
        context_injection="PROTOCOL: Group Chat. Stay silent unless @mentioned.",
        personality_override="Technical, concise, operations-focused.",
    )
    assert not res_set.is_error
    assert "Successfully updated session metadata for chat '-1004453403218'" in res_set
    assert "Staff Group" in res_set

    # 3. Get
    res_get = await tool.execute(action="get", chat_id="-1004453403218")
    assert not res_get.is_error
    assert "Staff Group" in res_get
    assert "Stay silent" in res_get

    # 4. List populated
    res_list2 = await tool.execute(action="list")
    assert not res_list2.is_error
    assert "-1004453403218" in res_list2
    assert "Staff Group" in res_list2

    # 5. Remove
    res_del = await tool.execute(action="remove", chat_id="-1004453403218")
    assert not res_del.is_error
    assert "Successfully removed" in res_del

    # 6. Get after remove
    res_get2 = await tool.execute(action="get", chat_id="-1004453403218")
    assert "No session metadata found" in res_get2


@pytest.mark.asyncio
async def test_update_session_metadata_tool_validation(tmp_path: Path) -> None:
    tool = UpdateSessionMetadataTool(file_path=tmp_path / "meta.json")

    # Missing chat_id for set
    res_err = await tool.execute(action="set", label="Foo")
    assert res_err.is_error
    assert "chat_id is required" in res_err

    # Unknown action
    res_err2 = await tool.execute(action="unknown")
    assert res_err2.is_error
    assert "Unknown action" in res_err2
