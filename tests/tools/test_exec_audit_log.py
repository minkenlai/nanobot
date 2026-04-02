from pathlib import Path

import pytest

from nanobot.agent.tools.shell import ExecTool


@pytest.mark.asyncio
async def test_exec_records_to_audit_log(tmp_path, monkeypatch):
    # Setup: change to tmp_path to capture audit.log in a clean place
    monkeypatch.chdir(tmp_path)

    tool = ExecTool()
    command = "echo 'audit test'"
    cwd = str(tmp_path)

    # Execute
    await tool.execute(command=command, working_dir=cwd)

    # Verify: logs/audit.log should be in the current process directory
    audit_log = Path("logs") / "audit.log"
    assert audit_log.exists()
    content = audit_log.read_text()
    assert f"CWD: {cwd} | CMD: {command}" in content
