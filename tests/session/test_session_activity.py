from datetime import datetime, timedelta
from pathlib import Path

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import RuntimeEventContext, UserInputAccepted
from nanobot.session.activity import (
    SessionActivityTracker,
    load_session_activity,
)


def test_session_activity_record_and_file_creation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tracker = SessionActivityTracker(workspace, window_minutes=30)

    now = datetime.now().astimezone()
    payload = tracker.record_activity(
        channel="telegram",
        session_id="telegram:12345",
        timestamp=now,
    )

    assert payload["channel"] == "telegram"
    assert payload["session_id"] == "telegram:12345"
    assert payload["last_activity_timestamp"] == now.isoformat()
    assert payload["active_sessions"]["telegram:12345"] == now.isoformat()
    assert payload["window_minutes"] == 30
    assert "activity_sessions" not in payload
    assert "active_session_ids" not in payload

    # Verify file was written to disk and can be read by load_session_activity
    disk_data = load_session_activity(workspace)
    assert disk_data is not None
    assert disk_data["channel"] == "telegram"
    assert disk_data["session_id"] == "telegram:12345"
    assert disk_data["last_activity_timestamp"] == now.isoformat()
    assert disk_data["active_sessions"]["telegram:12345"] == now.isoformat()


def test_session_activity_multiple_sessions(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    tracker = SessionActivityTracker(workspace, window_minutes=60)

    t1 = datetime.now().astimezone() - timedelta(minutes=10)
    t2 = datetime.now().astimezone() - timedelta(minutes=5)
    t3 = datetime.now().astimezone()

    tracker.record_activity(channel="telegram", session_id="telegram:user1", timestamp=t1)
    tracker.record_activity(channel="whatsapp", session_id="whatsapp:+123456", timestamp=t2)
    tracker.record_activity(channel="websocket", session_id="websocket:topic-99", timestamp=t3)

    data = load_session_activity(workspace)
    assert data is not None
    assert data["channel"] == "websocket"
    assert data["session_id"] == "websocket:topic-99"
    assert len(data["active_sessions"]) == 3
    assert data["active_sessions"]["telegram:user1"] == t1.isoformat()
    assert data["active_sessions"]["whatsapp:+123456"] == t2.isoformat()
    assert data["active_sessions"]["websocket:topic-99"] == t3.isoformat()
    assert set(data["active_sessions"].keys()) == {"telegram:user1", "websocket:topic-99", "whatsapp:+123456"}


def test_session_activity_sliding_window_pruning(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    # 15-minute window
    tracker = SessionActivityTracker(workspace, window_minutes=15)

    base_time = datetime.now().astimezone()
    old_time = base_time - timedelta(minutes=25)  # expired (> 15m)
    recent_time = base_time  # active

    tracker.record_activity(channel="telegram", session_id="telegram:old", timestamp=old_time)
    tracker.record_activity(channel="slack", session_id="slack:recent", timestamp=recent_time)

    # After recent activity, telegram:old should be pruned because it's 20m old (> 15m window)
    data = load_session_activity(workspace)
    assert data is not None
    assert "telegram:old" not in data["active_sessions"]
    assert "slack:recent" in data["active_sessions"]
    assert list(data["active_sessions"].keys()) == ["slack:recent"]


def test_session_activity_load_existing_on_startup(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    t1 = datetime.now().astimezone() - timedelta(minutes=5)

    # First tracker creates and writes file
    tracker1 = SessionActivityTracker(workspace, window_minutes=60)
    tracker1.record_activity(channel="discord", session_id="discord:chan1", timestamp=t1)

    # Second tracker starts up and loads existing file
    tracker2 = SessionActivityTracker(workspace, window_minutes=60)
    assert tracker2.last_channel == "discord"
    assert tracker2.last_session_id == "discord:chan1"
    assert tracker2.last_activity_timestamp == t1.isoformat()
    assert "discord:chan1" in tracker2.active_sessions


async def test_session_activity_bus_subscription(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    bus = MessageBus()
    tracker = SessionActivityTracker(workspace, window_minutes=30)
    tracker.attach_to_bus(bus)

    # Simulate inbound user message and publication of UserInputAccepted
    msg = InboundMessage(
        channel="telegram",
        sender_id="12345",
        chat_id="67890",
        content="hello bot",
    )

    event = UserInputAccepted(
        context=RuntimeEventContext(
            channel=msg.channel,
            chat_id=msg.chat_id,
            session_key="telegram:67890",
            metadata={},
        ),
        content=msg.content,
    )

    await bus.publish(event)

    data = load_session_activity(workspace)
    assert data is not None
    assert data["channel"] == "telegram"
    assert data["session_id"] == "telegram:67890"
    assert "telegram:67890" in data["active_sessions"]


def test_session_manager_save_records_activity(tmp_path: Path) -> None:
    from nanobot.session.manager import SessionManager

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sessions_root = tmp_path / "sessions_root"
    sessions_root.mkdir()

    mgr = SessionManager(workspace, sessions_root=sessions_root)
    session = mgr.get_or_create("api:default")
    session.messages.append({
        "role": "user",
        "content": "Hello Guide assistant",
        "timestamp": datetime.now().astimezone().isoformat(),
    })
    session.messages.append({
        "role": "assistant",
        "content": "Hello, welcome to our studio!",
        "timestamp": datetime.now().astimezone().isoformat(),
    })

    mgr.save(session)

    data = load_session_activity(workspace)
    assert data is not None
    assert data["channel"] == "api"
    assert data["session_id"] == "api:default"
    assert "api:default" in data["active_sessions"]


def test_session_manager_save_ignores_system_sessions(tmp_path: Path) -> None:
    from nanobot.session.manager import SessionManager

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sessions_root = tmp_path / "sessions_root"
    sessions_root.mkdir()

    mgr = SessionManager(workspace, sessions_root=sessions_root)
    session = mgr.get_or_create("system:heartbeat")
    session.messages.append({
        "role": "user",
        "content": "Heartbeat check",
        "timestamp": datetime.now().astimezone().isoformat(),
    })
    mgr.save(session)

    assert load_session_activity(workspace) is None
