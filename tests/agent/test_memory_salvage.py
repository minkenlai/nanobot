import json

from nanobot.agent.memory import _normalize_save_memory_args


def test_normalize_save_memory_args_valid_json():
    """Test standard valid JSON arguments."""
    args = {"history_entry": "test entry", "memory_update": "test update"}
    args_json = json.dumps(args)
    assert _normalize_save_memory_args(args_json) == args


def test_normalize_save_memory_args_salvage_json_from_text():
    """Test salvaging a JSON block from conversational text."""
    args = {"history_entry": "salvaged entry", "memory_update": "salvaged update"}
    conversational_text = f"Sure, here is your summary:\n\n{json.dumps(args)}\n\nI hope that helps!"
    assert _normalize_save_memory_args(conversational_text) == args


def test_normalize_save_memory_args_malformed_json():
    """Test that truly malformed JSON (not salvageable) returns None."""
    malformed_text = "This is not JSON { at all"
    assert _normalize_save_memory_args(malformed_text) is None


def test_normalize_save_memory_args_nested_json_salvage():
    """Test salvaging a specific JSON block when multiple exist (takes the first)."""
    args1 = {"a": 1}
    args2 = {"b": 2}
    dual_json = f"First: {json.dumps(args1)} Second: {json.dumps(args2)}"
    # Current regex handles the first match
    assert _normalize_save_memory_args(dual_json) == args1
