from unittest.mock import MagicMock

from nanobot.agent.loop import AgentLoop
from nanobot.config.schema import Config
from nanobot.session.manager import Session


def test_frugality_nudge_threshold_messages():
    """Test that a nudge is added after reaching the message floor."""
    loop = MagicMock(spec=AgentLoop)
    loop.config = Config()
    loop.config.frugality.message_floor = 10
    loop.config.frugality.nudge_interval = 5

    # Mock memory consolidator
    loop.memory_consolidator = MagicMock()
    loop.memory_consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(1000, "src"))
    loop.context_window_tokens = 10000

    # Mock sessions
    loop.sessions = MagicMock()

    # Create a session with 12 messages (past floor of 10)
    session = Session(key="test", messages=[{"role": "user", "content": "hi"}] * 12)
    session.metadata = {}

    # Run the nudge logic
    content = "Hello there!"
    # Call the real method on the mock object
    result = AgentLoop._maybe_add_frugality_nudge(loop, session, content)

    assert "💡 **Frugality Tip:**" in result
    assert "12 messages" in result
    assert "10% context" in result
    assert session.metadata["last_frugality_nudge"] == 12


def test_frugality_nudge_below_threshold():
    """Test that no nudge is added if below thresholds."""
    loop = MagicMock(spec=AgentLoop)
    loop.config = Config()
    loop.config.frugality.message_floor = 50
    loop.config.frugality.context_floor_pct = 60

    # Mock memory consolidator
    loop.memory_consolidator = MagicMock()
    loop.memory_consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(1000, "src"))
    loop.context_window_tokens = 10000  # 10% context

    session = Session(key="test", messages=[{"role": "user", "content": "hi"}] * 5)
    session.metadata = {}

    content = "Hello!"
    result = AgentLoop._maybe_add_frugality_nudge(loop, session, content)

    assert result == content
    assert "last_frugality_nudge" not in session.metadata


def test_frugality_nudge_interval_respect():
    """Test that nudges respect the configured interval."""
    loop = MagicMock(spec=AgentLoop)
    loop.config = Config()
    loop.config.frugality.message_floor = 10
    loop.config.frugality.nudge_interval = 10

    # Mock memory consolidator
    loop.memory_consolidator = MagicMock()
    loop.memory_consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(1000, "src"))
    loop.context_window_tokens = 10000

    loop.sessions = MagicMock()

    # Session already nudged at message 12
    session = Session(key="test", messages=[{"role": "user", "content": "hi"}] * 15)
    session.metadata = {"last_frugality_nudge": 12}

    content = "Hello!"
    # 15 - 12 = 3 < interval of 10. Should NOT nudge.
    result = AgentLoop._maybe_add_frugality_nudge(loop, session, content)

    assert result == content
    assert session.metadata["last_frugality_nudge"] == 12
