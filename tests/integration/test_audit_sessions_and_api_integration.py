"""End-to-end integration tests for Guide Node API security ingress, user ID, and guide_audit tool."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from nanobot.agent.tools.audit_sessions import AuditSessionsTool
from nanobot.api.server import (
    API_SESSION_KEY,
    create_app,
)

try:
    from aiohttp.test_utils import TestClient, TestServer

    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

pytest_plugins = ("pytest_asyncio",)

API_KEY = "secret"
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}


def _make_mock_agent(response_text: str = "Hello from Guide node!") -> MagicMock:
    agent = MagicMock()
    agent.process_direct = AsyncMock(return_value=response_text)
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()
    agent._last_usage = {"prompt_tokens": 50, "completion_tokens": 20}
    return agent


@pytest.fixture(autouse=True)
def reset_server_state():
    # Note: Global state is handled inside the app or via fixture cleanup if necessary
    yield


@pytest_asyncio.fixture
async def api_client():
    if not HAS_AIOHTTP:
        pytest.skip("aiohttp not installed")
    agent = _make_mock_agent()
    app = create_app(
        agent,
        model_name="test-model",
        request_timeout=10.0,
        api_key=API_KEY,
        cors_origins=["https://widget.example.com"],
        max_turn_prompt_length=2000,
        rate_limit_ip_per_min=10,
        rate_limit_session_per_min=5,
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        yield client
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_openai_api_web_anon_session_identification(api_client: TestClient) -> None:
    headers = {**AUTH_HEADERS, "Origin": "https://widget.example.com"}
    payload = {
        "model": "nanobot",
        "messages": [{"role": "user", "content": "What are your business hours?"}],
    }
    resp = await api_client.post("/v1/chat/completions", json=payload, headers=headers)
    assert resp.status == 200
    assert resp.headers.get("Access-Control-Allow-Origin") == "https://widget.example.com"

    body = await resp.json()
    assert body["choices"][0]["message"]["content"] == "Hello from Guide node!"


@pytest.mark.asyncio
async def test_session_archiving_and_audit_discovery(tmp_path: Path) -> None:
    """Verify pre-reset session snapshot archiving and guide_audit archive discovery."""
    from nanobot.agent.tools.audit_sessions import AuditSessionsTool
    from nanobot.session.manager import SessionManager

    manager = SessionManager(tmp_path)
    session = manager.get_or_create("telegram:staff_1")
    session.add_message("user", "Staff question before reset")
    session.add_message("assistant", "Staff reply before reset")
    manager.save(session)

    archive_path = manager.archive_session_snapshot(session, reason="new_command")
    assert archive_path is not None
    assert archive_path.exists()
    assert "archives" in archive_path.parts

    # Scan with AuditSessionsTool
    tool = AuditSessionsTool(sessions_dirs=[manager.sessions_dir])
    sessions = tool.load_sessions([manager.sessions_dir])
    archived_sessions = [s for s in sessions if "Staff question before reset" in str(s.get("messages", []))]
    assert len(archived_sessions) >= 1

    # Prune expired archives
    pruned = tool.prune_expired_archives([manager.sessions_dir], retention_days=0)
    assert pruned == 1
    assert not archive_path.exists()


@pytest.mark.asyncio
async def test_guide_session_command_router_bypass() -> None:
    """Verify that Guide sessions bypass CommandRouter builtin slash commands."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.events import InboundMessage

    msg = InboundMessage(
        channel="telegram",
        sender_id="customer_1",
        chat_id="8466578140",
        content="/status",
        metadata={"node_type": "guide", "bot_identity": "guide"},
    )
    assert AgentLoop._is_guide_session(msg, "telegram:guide:8466578140") is True

    admin_msg = InboundMessage(
        channel="telegram",
        sender_id="staff_1",
        chat_id="8466578140",
        content="/status",
        metadata={"node_type": "primary"},
    )
    assert AgentLoop._is_guide_session(admin_msg, "telegram:8466578140") is False


@pytest.mark.asyncio
async def test_openai_api_prompt_ceiling_enforcement(api_client: TestClient) -> None:
    headers = AUTH_HEADERS
    long_prompt = "A" * 2100
    payload = {
        "model": "nanobot",
        "messages": [{"role": "user", "content": long_prompt}],
    }
    resp = await api_client.post("/v1/chat/completions", json=payload, headers=headers)
    assert resp.status == 400
    body = await resp.json()
    assert "exceeds turn limit" in body["error"]["message"]


@pytest.mark.asyncio
async def test_openai_api_rate_limiter_burst(api_client: TestClient) -> None:
    headers = AUTH_HEADERS
    payload = {
        "model": "nanobot",
        "messages": [{"role": "user", "content": "Quick question"}],
    }

    status_codes: list[int] = []
    for _ in range(8):
        resp = await api_client.post("/v1/chat/completions", json=payload, headers=headers)
        status_codes.append(resp.status)

    # Rate limit session per min is 5: first 5 succeed (200), subsequent return 429
    assert status_codes[:5] == [200] * 5
    assert status_codes[5:] == [429] * 3


@pytest.mark.asyncio
async def test_audit_sessions_end_to_end_report_and_checkpoint_dispatch(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    reports_dir = tmp_path / "audit_reports"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    # Seed sample session
    s1 = {
        "key": "api:web:anon_9f8e7d",
        "created_at": "2026-08-09T01:00:00.000000",
        "updated_at": "2026-08-09T01:05:00.000000",
        "messages": [
            {"role": "user", "content": "Help me login", "timestamp": "2026-08-09T01:00:00.000000"},
            {"role": "assistant", "content": "Click reset password.", "timestamp": "2026-08-09T01:01:00.000000"},
        ],
    }
    (sessions_dir / "api:web:anon_9f8e7d.json").write_text(json.dumps(s1), encoding="utf-8")

    tool = AuditSessionsTool(sessions_dirs=[sessions_dir])

    ctx = MagicMock()
    ctx.config.audit_sessions.reports_dir = str(reports_dir)
    ctx.config.audit_sessions.dispatch_whatsapp_jid = "120363000000000000@g.us"
    ctx.config.audit_sessions.dispatch_telegram_chat_id = ""

    bus_mock = MagicMock()
    bus_mock.publish_outbound = AsyncMock()
    ctx.bus = bus_mock

    res = await tool.execute(ctx, action="generate_report", timeframe="all")
    assert not res.is_error
    assert "Daily Audit Report Generated Successfully" in res

    # Verify HTML report file
    html_files = list(reports_dir.glob("*.html"))
    assert len(html_files) == 1
    content = html_files[0].read_text(encoding="utf-8")
    assert "Daily Guide Audit Report" in content
    assert "api:web:anon_9f8e7d" in content

    # Verify Audit Checkpoint File
    checkpoint_file = reports_dir / ".audit_checkpoint.json"
    assert checkpoint_file.exists()
    checkpoint_data = json.loads(checkpoint_file.read_text(encoding="utf-8"))
    assert checkpoint_data["sessions"]["api:web:anon_9f8e7d"] == "2026-08-09T01:01:00.000000"

    # Verify MessageBus Dispatch Outbound Event
    bus_mock.publish_outbound.assert_awaited_once()
    outbound_msg = bus_mock.publish_outbound.call_args[0][0]
    assert outbound_msg.channel == "whatsapp"
    assert outbound_msg.chat_id == "120363000000000000@g.us"
    assert "Daily Guide Audit Summary" in outbound_msg.content


@pytest.mark.asyncio
async def test_audit_sessions_api_endpoint_response(api_client) -> None:
    resp = await api_client.get("/v1/audit_sessions?action=list&timeframe=all", headers=AUTH_HEADERS)
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "ok"
    assert "sessions" in data


@pytest.mark.asyncio
async def test_cmd_new_archiving_end_to_end(tmp_path: Path) -> None:
    """Verify end-to-end flow: staff executes /new, session is archived to sessions/archives/, and audit_sessions generates report containing pre-reset messages."""
    from datetime import datetime
    from nanobot.agent.tools.audit_sessions import AuditSessionsTool
    from nanobot.bus.events import InboundMessage
    from nanobot.command import CommandContext
    from nanobot.command.builtin import cmd_new
    from nanobot.session.manager import SessionManager

    sessions_dir = tmp_path / "sessions"
    reports_dir = tmp_path / "audit_reports"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    manager = SessionManager(tmp_path)
    session = manager.get_or_create("telegram:staff_1")
    manager = SessionManager(tmp_path)
    sessions_dir = manager.sessions_dir
    reports_dir = tmp_path / "audit_reports"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    session_key = "telegram:guide:123456"
    session = manager.get_or_create(session_key)
    session.add_message("user", "Pre-reset staff turn 1", timestamp="2026-08-10T10:00:00.000000")
    session.add_message("assistant", "Pre-reset assistant turn 1", timestamp="2026-08-10T10:01:00.000000")
    manager.save(session)

    inbound = InboundMessage(channel="telegram", sender_id="123456", chat_id="123456", content="/new")
    cmd_ctx = CommandContext(
        msg=inbound,
        session=session,
        key=session_key,
        raw="/new",
        loop=MagicMock(sessions=manager, _cancel_active_tasks=AsyncMock(), schedule_background=MagicMock()),
    )
    res_msg = await cmd_new(cmd_ctx)
    assert res_msg.content == "New session started."
    assert len(session.messages) == 0  # Active session cleared

    # Verify archive file created in sessions/archives/
    archive_dir = sessions_dir / "archives"
    assert archive_dir.exists()
    archive_files = list(archive_dir.glob("*.json"))
    assert len(archive_files) == 1

    # Run AuditSessionsTool report generation over sessions_dir
    tool = AuditSessionsTool(sessions_dirs=[sessions_dir])
    ctx = MagicMock()
    ctx.config.audit_sessions.reports_dir = str(reports_dir)
    ctx.config.audit_sessions.dispatch_whatsapp_jid = ""
    ctx.config.audit_sessions.dispatch_telegram_chat_id = ""

    report_res = await tool.execute(ctx, action="generate_report", timeframe="all")
    assert "Daily Audit Report Generated Successfully" in report_res

    html_content = (reports_dir / f"{datetime.now().strftime('%Y-%m-%d')}.html").read_text(encoding="utf-8")
    assert "Pre-reset staff turn 1" in html_content


@pytest.mark.asyncio
async def test_reset_session_tool(tmp_path: Path) -> None:
    """Verify ResetSessionTool archives session history and resets active context."""
    from nanobot.agent.tools.sessions import ResetSessionTool
    from nanobot.session.manager import SessionManager

    manager = SessionManager(tmp_path)
    session = manager.get_or_create("telegram:guide:8466578140")
    session.add_message("user", "User asked to forget chat context")
    session.add_message("assistant", "Assistant response before reset")
    manager.save(session)

    tool = ResetSessionTool(manager)
    ctx = MagicMock()
    ctx.session_key = "telegram:guide:8466578140"
    ctx.sessions = manager

    res = await tool.execute(ctx, reason="user_requested_reset")
    assert not res.is_error
    assert "Chat history reset to a fresh start." in str(res)
    assert len(session.messages) == 0

    archives_dir = manager.sessions_dir / "archives"
    assert archives_dir.exists()
    archive_files = list(archives_dir.glob("*.json"))
    assert len(archive_files) == 1
    assert "user_requested_reset" in archive_files[0].name


@pytest.mark.asyncio
async def test_web_session_idle_reset(tmp_path: Path) -> None:
    """Verify AgentLoop automatically resets web sessions after idle threshold."""
    from datetime import datetime, timedelta
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.events import InboundMessage
    from nanobot.session.manager import SessionManager

    manager = SessionManager(tmp_path)
    session = manager.get_or_create("api:web:anon_123")
    session.add_message("user", "Web message from 40 mins ago")
    # Backdate session updated_at timestamp to 40 minutes ago
    session.updated_at = datetime.now() - timedelta(minutes=40)
    manager.save(session)

    loop = MagicMock(spec=AgentLoop)
    loop.sessions = manager
    loop.config = MagicMock()
    loop.config.audit_sessions.web_session_idle_reset_minutes = 30

    msg = InboundMessage(channel="web", sender_id="anon_123", chat_id="anon_123", content="Fresh message after gap")
    AgentLoop._check_web_session_idle_reset(loop, "api:web:anon_123", msg)

    # Session should now be cleared of the 40-min-old message and archived
    cleared_session = manager.get_or_create("api:web:anon_123")
    assert len(cleared_session.messages) == 0

    archives_dir = manager.sessions_dir / "archives"
    assert archives_dir.exists()
    archive_files = list(archives_dir.glob("*.json"))
    assert len(archive_files) == 1
    assert "idle_timeout" in archive_files[0].name


@pytest.mark.asyncio
async def test_reset_session_mid_turn_persistence_prevention(tmp_path: Path) -> None:
    """Verify that mid-turn session reset prevents saving turn-tail messages into active history."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools.sessions import ResetSessionTool
    from nanobot.session.manager import SessionManager

    manager = SessionManager(tmp_path)
    session = manager.get_or_create("telegram:guide:8466578140")
    session.add_message("user", "Hello prior message")
    manager.save(session)

    # Tool executes mid-turn
    tool = ResetSessionTool(manager)
    ctx = MagicMock()
    ctx.session_key = "telegram:guide:8466578140"
    ctx.sessions = manager

    await tool.execute(ctx, reason="user_requested_reset")

    # Simulate _save_turn running at turn completion with turn 1's tail messages
    loop = MagicMock(spec=AgentLoop)
    loop.max_tool_result_chars = 1000
    fake_turn_msgs = [
        {"role": "user", "content": "let's reset cleanly"},
        {"role": "assistant", "tool_calls": [{"id": "tc1", "function": {"name": "reset_session"}}]},
        {"role": "tool", "tool_call_id": "tc1", "content": "Chat history reset to a fresh start."},
        {"role": "assistant", "content": "Conversation context has been reset!"},
    ]

    # Save turn with skip=1
    AgentLoop._save_turn(loop, session, fake_turn_msgs, skip=1)

    # Session messages must stay EMPTY
    assert len(session.messages) == 0
