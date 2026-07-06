"""Tests for flatten_tool_choice logic in OpenAICompatClient._build_kwargs.

Validates that tool_choice dict flattening works correctly per spec and
does not interfere with string tool_choice values.
"""

from __future__ import annotations

import pytest

from nanobot.providers.openai_compat_provider import OpenAICompatClient
from nanobot.providers.registry import ProviderSpec

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TOOL = {"type": "function", "function": {"name": "exec", "description": "run cmd"}}
MESSAGES = [{"role": "user", "content": "hello"}]


def _spec(flatten_tool_choice: bool = False, **kwargs) -> ProviderSpec:
    """Create a minimal ProviderSpec for testing."""
    return ProviderSpec(
        name="test_provider",
        keywords=("test",),
        env_key="TEST_API_KEY",
        flatten_tool_choice=flatten_tool_choice,
        **kwargs,
    )


def _make_client(spec: ProviderSpec | None = None) -> OpenAICompatClient:
    """Build a client with a fake AsyncOpenAI so we don't hit the network."""
    import os

    old = os.environ.pop("TEST_API_KEY", None)
    try:
        return OpenAICompatClient(
            api_key="sk-test",
            spec=spec,
            default_model="test-model",
        )
    finally:
        if old is not None:
            os.environ["TEST_API_KEY"] = old


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFlattenToolChoice:
    """Scenarios for the flatten_tool_choice feature."""

    # --- 1. flatten_tool_choice=False: dict stays dict ---

    def test_dict_tool_choice_stays_dict_when_not_flattening(self):
        spec = _spec(flatten_tool_choice=False)
        client = _make_client(spec)

        tc = {"type": "function", "function": {"name": "exec"}}
        kwargs = client._build_kwargs(
            messages=MESSAGES,
            tools=[TOOL],
            model=None,
            max_tokens=1024,
            temperature=0.7,
            reasoning_effort=None,
            tool_choice=tc,
        )

        assert kwargs["tool_choice"] == tc

    def test_none_tool_choice_defaults_to_auto_when_not_flattening(self):
        """tool_choice=None with no tools means no tool_choice key in kwargs.
        tool_choice=None WITH tools defaults to 'auto'."""
        spec = _spec(flatten_tool_choice=False)
        client = _make_client(spec)

        kwargs = client._build_kwargs(
            messages=MESSAGES,
            tools=[TOOL],
            model=None,
            max_tokens=1024,
            temperature=0.7,
            reasoning_effort=None,
            tool_choice=None,
        )

        assert kwargs["tool_choice"] == "auto"

    # --- 2. flatten_tool_choice=True: dict with function name → string ---

    def test_dict_tool_choice_flattened_to_function_name(self):
        spec = _spec(flatten_tool_choice=True)
        client = _make_client(spec)

        tc = {"type": "function", "function": {"name": "exec"}}
        kwargs = client._build_kwargs(
            messages=MESSAGES,
            tools=[TOOL],
            model=None,
            max_tokens=1024,
            temperature=0.7,
            reasoning_effort=None,
            tool_choice=tc,
        )

        assert kwargs["tool_choice"] == "exec"

    def test_dict_tool_choice_flattened_with_nested_function(self):
        """The flattening logic only reads tc['function']['name']."""
        spec = _spec(flatten_tool_choice=True)
        client = _make_client(spec)

        tc = {
            "type": "function",
            "function": {"name": "search_web", "description": "search"},
        }
        kwargs = client._build_kwargs(
            messages=MESSAGES,
            tools=[TOOL],
            model=None,
            max_tokens=1024,
            temperature=0.7,
            reasoning_effort=None,
            tool_choice=tc,
        )

        assert kwargs["tool_choice"] == "search_web"

    # --- 3. flatten_tool_choice=True: dict missing function name → "auto" ---

    def test_dict_tool_choice_missing_function_falls_back_to_auto(self):
        spec = _spec(flatten_tool_choice=True)
        client = _make_client(spec)

        tc = {"type": "function"}  # no "function" key
        kwargs = client._build_kwargs(
            messages=MESSAGES,
            tools=[TOOL],
            model=None,
            max_tokens=1024,
            temperature=0.7,
            reasoning_effort=None,
            tool_choice=tc,
        )

        assert kwargs["tool_choice"] == "auto"

    def test_dict_tool_choice_function_missing_name_falls_back_to_auto(self):
        """tc = {'function': {}} — function dict exists but has no name."""
        spec = _spec(flatten_tool_choice=True)
        client = _make_client(spec)

        tc = {"type": "function", "function": {}}
        kwargs = client._build_kwargs(
            messages=MESSAGES,
            tools=[TOOL],
            model=None,
            max_tokens=1024,
            temperature=0.7,
            reasoning_effort=None,
            tool_choice=tc,
        )

        assert kwargs["tool_choice"] == "auto"

    def test_dict_tool_choice_function_name_empty_string_falls_back_to_auto(self):
        """tc = {'function': {'name': ''}} — empty name is falsy."""
        spec = _spec(flatten_tool_choice=True)
        client = _make_client(spec)

        tc = {"type": "function", "function": {"name": ""}}
        kwargs = client._build_kwargs(
            messages=MESSAGES,
            tools=[TOOL],
            model=None,
            max_tokens=1024,
            temperature=0.7,
            reasoning_effort=None,
            tool_choice=tc,
        )

        assert kwargs["tool_choice"] == "auto"

    # --- 4. String tool_choice remains untouched regardless of flatten flag ---

    @pytest.mark.parametrize("tc_value", ["required", "none", "auto"])
    def test_string_tool_choice_preserved_when_flattening(self, tc_value: str):
        spec = _spec(flatten_tool_choice=True)
        client = _make_client(spec)

        kwargs = client._build_kwargs(
            messages=MESSAGES,
            tools=[TOOL],
            model=None,
            max_tokens=1024,
            temperature=0.7,
            reasoning_effort=None,
            tool_choice=tc_value,
        )

        assert kwargs["tool_choice"] == tc_value

    @pytest.mark.parametrize("tc_value", ["required", "none", "auto"])
    def test_string_tool_choice_preserved_when_not_flattening(self, tc_value: str):
        spec = _spec(flatten_tool_choice=False)
        client = _make_client(spec)

        kwargs = client._build_kwargs(
            messages=MESSAGES,
            tools=[TOOL],
            model=None,
            max_tokens=1024,
            temperature=0.7,
            reasoning_effort=None,
            tool_choice=tc_value,
        )

        assert kwargs["tool_choice"] == tc_value

    # --- Edge: no tools → no tool_choice in kwargs ---

    def test_no_tools_means_no_tool_choice_key(self):
        spec = _spec(flatten_tool_choice=True)
        client = _make_client(spec)

        kwargs = client._build_kwargs(
            messages=MESSAGES,
            tools=None,
            model=None,
            max_tokens=1024,
            temperature=0.7,
            reasoning_effort=None,
            tool_choice={"type": "function", "function": {"name": "exec"}},
        )

        assert "tool_choice" not in kwargs

    # --- Edge: spec=None → flatten_tool_choice never triggers ---

    def test_no_spec_dict_tool_choice_stays_dict(self):
        """When spec is None, flatten_tool_choice can't be checked; dict passes through."""
        client = _make_client(spec=None)

        tc = {"type": "function", "function": {"name": "exec"}}
        kwargs = client._build_kwargs(
            messages=MESSAGES,
            tools=[TOOL],
            model=None,
            max_tokens=1024,
            temperature=0.7,
            reasoning_effort=None,
            tool_choice=tc,
        )

        assert kwargs["tool_choice"] == tc
