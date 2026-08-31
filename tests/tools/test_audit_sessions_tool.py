"""Tests for the GuideAuditTool native tool."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.tools.audit_sessions import AuditSessionsTool


@pytest.fixture
def mock_sessions_dir(tmp_path: Path) -> Path:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    # Sample 1: Web anon session with normal messages
    s1 = {
        "key": "api:web:anon_9f8e7d",
        "created_at": "2026-08-08T04:00:00.000000",
        "updated_at": "2026-08-08T04:05:00.000000",
        "messages": [
            {"role": "user", "content": "What are your opening hours?", "timestamp": "2026-08-08T04:00:00.000000"},
            {"role": "assistant", "content": "We are open 9am to 5pm daily.", "timestamp": "2026-08-08T04:00:02.000000"},
        ],
    }
    (sessions_dir / "api:web:anon_9f8e7d.json").write_text(json.dumps(s1), encoding="utf-8")

    # Sample 2: WhatsApp user session with confusion/error
    s2 = {
        "key": "whatsapp:+15550199",
        "created_at": "2026-08-08T05:00:00.000000",
        "updated_at": "2026-08-08T05:10:00.000000",
        "messages": [
            {"role": "user", "content": "Can I book a table?", "timestamp": "2026-08-08T05:00:00.000000"},
            {"role": "assistant", "content": "Sorry, I am confused by your request and failed to process.", "timestamp": "2026-08-08T05:00:02.000000"},
        ],
    }
    (sessions_dir / "whatsapp:+15550199.json").write_text(json.dumps(s2), encoding="utf-8")

    # Sample 3: Telegram group session
    s3 = {
        "key": "telegram:-100123456789",
        "created_at": "2026-08-08T06:00:00.000000",
        "updated_at": "2026-08-08T06:15:00.000000",
        "messages": [
            {"role": "user", "content": "Hello team!", "timestamp": "2026-08-08T06:00:00.000000"},
            {"role": "assistant", "content": "Hello! How can I help the group today?", "timestamp": "2026-08-08T06:00:02.000000"},
        ],
    }
    (sessions_dir / "telegram:-100123456789.json").write_text(json.dumps(s3), encoding="utf-8")

    return sessions_dir


@pytest.mark.asyncio
async def test_audit_sessions_list_action(mock_sessions_dir: Path) -> None:
    tool = AuditSessionsTool(sessions_dirs=[mock_sessions_dir])
    res = await tool.execute(MagicMock(), action="list", channel="all", timeframe="all")
    assert not res.is_error
    assert "Session Audit List" in res
    assert "api:web:anon_9f8e7d" in res
    assert "whatsapp:+15550199" in res
    assert "telegram:-100123456789" in res


@pytest.mark.asyncio
async def test_audit_sessions_inspect_action(mock_sessions_dir: Path) -> None:
    tool = AuditSessionsTool(sessions_dirs=[mock_sessions_dir])
    res = await tool.execute(MagicMock(), action="inspect", session_id="anon_9f8e7d")
    assert not res.is_error
    assert "api:web:anon_9f8e7d" in res
    assert "What are your opening hours?" in res
    assert "We are open 9am to 5pm daily." in res


@pytest.mark.asyncio
async def test_audit_sessions_summary_action(mock_sessions_dir: Path) -> None:
    tool = AuditSessionsTool(sessions_dirs=[mock_sessions_dir])
    res = await tool.execute(MagicMock(), action="summary", timeframe="all")
    assert not res.is_error
    assert "Session Summary Report" in res
    assert "Total Matching Sessions" in res
    assert "whatsapp" in res
    assert "telegram" in res
    assert "web" in res


@pytest.mark.asyncio
async def test_audit_sessions_flagged_action(mock_sessions_dir: Path) -> None:
    tool = AuditSessionsTool(sessions_dirs=[mock_sessions_dir])
    res = await tool.execute(MagicMock(), action="flagged", timeframe="all")
    assert not res.is_error
    assert "Flagged Sessions" in res
    assert "whatsapp:+15550199" in res


@pytest.mark.asyncio
async def test_audit_sessions_error_cases(mock_sessions_dir: Path) -> None:
    tool = AuditSessionsTool(sessions_dirs=[mock_sessions_dir])

    # Missing session_id for inspect action
    res = await tool.execute(MagicMock(), action="inspect")
    assert res.is_error
    assert "session_id parameter is required" in res

    # Unknown session_id
    res = await tool.execute(MagicMock(), action="inspect", session_id="nonexistent_id")
    assert res.is_error
    assert "Session matching 'nonexistent_id' not found." in res

    # Unknown action
    res = await tool.execute(MagicMock(), action="invalid_action")
    assert res.is_error
    assert "Unknown action 'invalid_action'" in res


@pytest.mark.asyncio
async def test_audit_sessions_generate_report_and_dispatch(mock_sessions_dir: Path, tmp_path: Path) -> None:
    from unittest.mock import AsyncMock

    reports_dir = tmp_path / "reports"
    tool = AuditSessionsTool(sessions_dirs=[mock_sessions_dir])

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
    assert reports_dir.exists()

    html_files = list(reports_dir.glob("*.html"))
    assert len(html_files) == 1
    content = html_files[0].read_text(encoding="utf-8")
    assert "Daily Guide Audit Report" in content
    assert "api:web:anon_9f8e7d" in content

    # Check WhatsApp dispatch
    bus_mock.publish_outbound.assert_awaited_once()
    outbound_msg = bus_mock.publish_outbound.call_args[0][0]
    assert outbound_msg.channel == "whatsapp"
    assert outbound_msg.chat_id == "120363000000000000@g.us"
    assert "Daily Guide Audit Summary" in outbound_msg.content

    # Check Audit Checkpoint File
    checkpoint_file = reports_dir / ".audit_checkpoint.json"
    assert checkpoint_file.exists()
    checkpoint_data = json.loads(checkpoint_file.read_text(encoding="utf-8"))
    assert "sessions" in checkpoint_data
    assert "api:web:anon_9f8e7d" in checkpoint_data["sessions"]
    assert checkpoint_data["sessions"]["api:web:anon_9f8e7d"] == "2026-08-08T04:00:02.000000"


def test_audit_sessions_enabled_toggle() -> None:
    ctx = MagicMock()
    ctx.config.audit_sessions.enabled = True
    assert AuditSessionsTool.enabled(ctx) is True

    ctx.config.audit_sessions.enabled = False
    assert AuditSessionsTool.enabled(ctx) is False


@pytest.mark.asyncio
async def test_audit_sessions_workspace_relative_session_dirs(tmp_path: Path) -> None:
    ws_dir = tmp_path / "workspace"
    rel_sessions_dir = ws_dir / "guide-workspace" / "sessions"
    rel_sessions_dir.mkdir(parents=True, exist_ok=True)

    s1 = {
        "key": "api:web:anon_rel123",
        "created_at": "2026-08-09T01:00:00.000000",
        "updated_at": "2026-08-09T01:05:00.000000",
        "messages": [
            {"role": "user", "content": "Testing workspace relative path", "timestamp": "2026-08-09T01:00:00.000000"},
        ],
    }
    (rel_sessions_dir / "api:web:anon_rel123.json").write_text(json.dumps(s1), encoding="utf-8")

    tool = AuditSessionsTool(sessions_dirs=["guide-workspace/sessions"])
    ctx = MagicMock()
    ctx.workspace = str(ws_dir)

    res = await tool.execute(ctx, action="list", timeframe="all")
    assert not res.is_error
    assert "api:web:anon_rel123" in res


@pytest.mark.asyncio
async def test_audit_sessions_jsonl_session_loading(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    jsonl_file = sessions_dir / "api_whatsapp_13105559999.jsonl"
    header = {"_type": "metadata", "key": "api:whatsapp:13105559999@s.whatsapp.net", "created_at": "2026-08-09T01:00:00.000000"}
    m1 = {"role": "user", "content": "What is the status of my order?", "timestamp": "2026-08-09T01:00:00.000000"}
    m2 = {"role": "assistant", "content": "Your order has shipped.", "timestamp": "2026-08-09T01:01:00.000000"}

    lines = [json.dumps(header), json.dumps(m1), json.dumps(m2)]
    jsonl_file.write_text("\n".join(lines), encoding="utf-8")

    tool = AuditSessionsTool(sessions_dirs=[sessions_dir])
    ctx = MagicMock()

    res = await tool.execute(ctx, action="list", timeframe="all")
    assert not res.is_error
    assert "api:whatsapp:13105559999@s.whatsapp.net" in res

    inspect_res = await tool.execute(ctx, action="inspect", session_id="13105559999")
    assert not inspect_res.is_error
    assert "What is the status of my order?" in inspect_res
    assert "Your order has shipped." in inspect_res


@pytest.mark.asyncio
async def test_audit_sessions_base64_filename_decoding(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    b64_filename = "whatsapp_120363428549747454@g.us.jsonl"
    jsonl_file = sessions_dir / b64_filename

    m1 = {"role": "user", "content": "Hello in whatsapp group", "timestamp": "2026-08-09T01:00:00.000000"}
    m2 = {"role": "assistant", "content": "Welcome to group support!", "timestamp": "2026-08-09T01:01:00.000000"}
    jsonl_file.write_text(f"{json.dumps(m1)}\n{json.dumps(m2)}", encoding="utf-8")

    tool = AuditSessionsTool(sessions_dirs=[sessions_dir])
    ctx = MagicMock()

    res = await tool.execute(ctx, action="list", timeframe="all", channel="whatsapp")
    assert not res.is_error
    assert "whatsapp:120363428549747454@g.us" in res

    inspect_res = await tool.execute(ctx, action="inspect", session_id="120363428549747454@g.us")
    assert not inspect_res.is_error
    assert "Hello in whatsapp group" in inspect_res


@pytest.mark.asyncio
async def test_audit_sessions_api_whatsapp_channel_filtering(tmp_path: Path) -> None:
    guide_dir = tmp_path / "guide-workspace" / "sessions"
    guide_dir.mkdir(parents=True, exist_ok=True)

    # Base64 for api:whatsapp:120363428549747454@g.us -> YXBpOndoYXRzYXBwOjEyMDM2MzQyODU0OTc0NzQ1NEBnLnVz.jsonl
    b64_filename = "YXBpOndoYXRzYXBwOjEyMDM2MzQyODU0OTc0NzQ1NEBnLnVz.jsonl"
    jsonl_file = guide_dir / b64_filename

    m1 = {"role": "user", "content": "API query from Guide node", "timestamp": "2026-08-09T02:00:00.000000"}
    m2 = {"role": "assistant", "content": "Response from Guide node", "timestamp": "2026-08-09T02:01:00.000000"}
    jsonl_file.write_text(f"{json.dumps(m1)}\n{json.dumps(m2)}", encoding="utf-8")

    tool = AuditSessionsTool(sessions_dirs=[guide_dir])
    ctx = MagicMock()

    # Query channel="whatsapp"
    res = await tool.execute(ctx, action="list", timeframe="all", channel="whatsapp")
    assert not res.is_error
    assert "api:whatsapp:120363428549747454@g.us" in res
    assert "Guide Node" in res


@pytest.mark.asyncio
async def test_audit_sessions_iso_timezone_timestamp_filtering(tmp_path: Path) -> None:
    from datetime import datetime

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    now_iso = datetime.now().isoformat() + "Z"
    jsonl_file = sessions_dir / "d2hhdHNhcHA6MTIwMzYzNDI4NTQ5NzQ3NDU0QGcudXM.jsonl"

    header = {"_type": "metadata", "key": "whatsapp:120363428549747454@g.us", "created_at": now_iso, "updated_at": now_iso}
    m1 = {"role": "user", "content": "Tz test message", "timestamp": now_iso}
    jsonl_file.write_text(f"{json.dumps(header)}\n{json.dumps(m1)}", encoding="utf-8")

    tool = AuditSessionsTool(sessions_dirs=[sessions_dir])
    ctx = MagicMock()

    res_7d = await tool.execute(ctx, action="list", timeframe="7d", channel="all")
    assert not res_7d.is_error
    assert "whatsapp:120363428549747454@g.us" in res_7d


@pytest.mark.asyncio
async def test_audit_sessions_webui_session_index_lookup(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    # Write .webui_session_index.json
    index_file = sessions_dir / ".webui_session_index.json"
    index_file.write_text(json.dumps({
        "telegram:8466578140": "dGVsZWdyYW06ODQ2NjU3ODE0MA.jsonl",
    }), encoding="utf-8")

    jsonl_file = sessions_dir / "dGVsZWdyYW06ODQ2NjU3ODE0MA.jsonl"
    m1 = {"role": "user", "content": "Hello telegram", "timestamp": "2026-08-09T01:00:00.000000"}
    jsonl_file.write_text(json.dumps(m1), encoding="utf-8")

    tool = AuditSessionsTool(sessions_dirs=[sessions_dir])
    ctx = MagicMock()

    res = await tool.execute(ctx, action="list", timeframe="all", channel="telegram")
    assert not res.is_error
    assert "telegram:8466578140" in res

    inspect_res = await tool.execute(ctx, action="inspect", session_id="telegram:8466578140")
    assert not inspect_res.is_error
    assert "Hello telegram" in inspect_res


@pytest.mark.asyncio
async def test_audit_sessions_auto_discovery_workspace_subdirectories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that AuditSessionsTool automatically discovers hashed workspace subdirectories and archives under the default sessions root."""
    root_sessions = tmp_path / "sessions"
    ws1_dir = root_sessions / "1111222233334444"
    ws2_dir = root_sessions / "5555666677778888"
    ws1_archives = ws1_dir / "archives"

    ws1_dir.mkdir(parents=True, exist_ok=True)
    ws2_dir.mkdir(parents=True, exist_ok=True)
    ws1_archives.mkdir(parents=True, exist_ok=True)

    # Workspace marker
    (ws1_dir / ".workspace").write_text("/home/user/my-workspace", encoding="utf-8")
    (ws2_dir / ".workspace").write_text("/home/user/guide-workspace", encoding="utf-8")

    # Sample sessions in workspace subdirectories
    s1 = {
        "key": "telegram:staff_1",
        "created_at": "2026-08-08T04:00:00.000000",
        "updated_at": "2026-08-08T04:05:00.000000",
        "messages": [{"role": "user", "content": "Query in primary node", "timestamp": "2026-08-08T04:00:00.000000"}],
    }
    (ws1_dir / "telegram:staff_1.json").write_text(json.dumps(s1), encoding="utf-8")

    s2 = {
        "key": "api:web:guide_user",
        "created_at": "2026-08-08T05:00:00.000000",
        "updated_at": "2026-08-08T05:05:00.000000",
        "messages": [{"role": "user", "content": "Query in guide node", "timestamp": "2026-08-08T05:00:00.000000"}],
    }
    (ws2_dir / "api:web:guide_user.json").write_text(json.dumps(s2), encoding="utf-8")

    # Archive session
    s_arch = {
        "key": "telegram:staff_1",
        "created_at": "2026-08-07T00:00:00.000000",
        "updated_at": "2026-08-07T00:05:00.000000",
        "messages": [{"role": "user", "content": "Old archived turn", "timestamp": "2026-08-07T00:00:00.000000"}],
    }
    (ws1_archives / "telegram_staff_1_20260807_000000_new_command.json").write_text(json.dumps(s_arch), encoding="utf-8")

    monkeypatch.setattr("nanobot.agent.tools.audit_sessions.get_runtime_subdir", lambda name: root_sessions)
    monkeypatch.setattr("nanobot.agent.tools.audit_sessions.get_legacy_sessions_dir", lambda: root_sessions)
    monkeypatch.setattr("nanobot.agent.tools.audit_sessions.get_sessions_dir", lambda: root_sessions)

    tool = AuditSessionsTool()  # Default: auto-discover without explicit sessions_dirs
    dirs = tool.resolve_session_dirs()

    assert ws1_dir in dirs or root_sessions in dirs
    sessions = tool.load_sessions(dirs)

    keys = [s["key"] for s in sessions]
    assert "telegram:staff_1" in keys
    assert "api:web:guide_user" in keys

    # Verify node detection via .workspace marker
    guide_session = next(s for s in sessions if s["key"] == "api:web:guide_user")
    assert guide_session["node_type"] == "guide"

