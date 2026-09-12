"""Tests for SessionMetadataStore persistence and lookup."""

from __future__ import annotations

import json
from pathlib import Path

from nanobot.session.metadata_store import SessionMetadataStore


def test_session_metadata_store_crud(tmp_path: Path) -> None:
    meta_file = tmp_path / "sessions_metadata.json"
    store = SessionMetadataStore(meta_file)

    assert store.load() == {}
    assert store.get("-1004453403218") is None
    assert store.format_injection("-1004453403218") is None

    # Create entry
    entry = store.set(
        "-1004453403218",
        label="Staff Group",
        context_injection="PROTOCOL: Group Chat. Stay silent unless @mentioned. Do not chime in on staff-to-staff coordination.",
        personality_override="Technical, concise, operations-focused.",
    )
    assert entry.label == "Staff Group"
    assert "Stay silent" in entry.context_injection
    assert "operations-focused" in entry.personality_override

    # Verify persisted on disk
    assert meta_file.exists()
    disk_data = json.loads(meta_file.read_text(encoding="utf-8"))
    assert "-1004453403218" in disk_data
    assert disk_data["-1004453403218"]["label"] == "Staff Group"

    # Reload fresh instance
    store2 = SessionMetadataStore(meta_file)
    entry2 = store2.get("-1004453403218")
    assert entry2 is not None
    assert entry2.label == "Staff Group"

    # Lookup with channel prefix
    assert store2.get("telegram:-1004453403218") is not None
    assert store2.get("telegram:-1004453403218").label == "Staff Group"

    # Formatted injection
    injection = store2.format_injection("-1004453403218")
    assert injection is not None
    assert "[Session Context: Staff Group]" in injection
    assert "PROTOCOL: Group Chat" in injection
    assert "Personality: Technical, concise, operations-focused." in injection

    # Partial update
    store.set("-1004453403218", personality_override="Playful, friendly.")
    updated = store.get("-1004453403218")
    assert updated is not None
    assert updated.label == "Staff Group"  # Preserved
    assert updated.personality_override == "Playful, friendly."

    # Delete
    assert store.delete("-1004453403218") is True
    assert store.get("-1004453403218") is None
    assert store.delete("-1004453403218") is False


def test_session_metadata_store_channel_prefixed_key(tmp_path: Path) -> None:
    meta_file = tmp_path / "sessions_metadata.json"
    store = SessionMetadataStore(meta_file)

    # Store with channel prefix
    store.set("whatsapp:12036304@g.us", label="Operations", context_injection="Only answer admin questions.")

    # Retrieve with bare chat_id
    entry = store.get("12036304@g.us")
    assert entry is not None
    assert entry.label == "Operations"

    # Retrieve with exact prefix
    entry2 = store.get("whatsapp:12036304@g.us")
    assert entry2 is not None
    assert entry2.label == "Operations"
