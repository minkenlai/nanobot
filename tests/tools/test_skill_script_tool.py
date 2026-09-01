"""Tests for RunSkillScriptTool."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from nanobot.agent.tools.skill_script import RunSkillScriptTool, _resolve_venv_python


@pytest.fixture
def mock_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    skills_dir = ws / "skills" / "my_skill" / "scripts"
    skills_dir.mkdir(parents=True, exist_ok=True)
    (ws / "skills" / "my_skill" / "SKILL.md").write_text(
        "---\nname: my_skill\ndescription: Test skill\n---\n# Test",
        encoding="utf-8",
    )

    # Sample script that prints args and python executable
    script = skills_dir / "test_script.py"
    script.write_text(
        "import sys\nprint('HELLO SKILL: ' + ' '.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    return ws


@pytest.mark.asyncio
async def test_run_skill_script_success(mock_workspace: Path) -> None:
    tool = RunSkillScriptTool(workspace=mock_workspace)
    res = await tool.execute(
        MagicMock(),
        skill_name="my_skill",
        script_name="test_script.py",
        args=["arg1", "arg2"],
    )
    assert not res.is_error
    assert "HELLO SKILL: arg1 arg2" in str(res)


@pytest.mark.asyncio
async def test_run_skill_script_prefers_workspace_venv(mock_workspace: Path) -> None:
    # Create fake .venv in workspace
    venv_bin = mock_workspace / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")
    venv_bin.mkdir(parents=True, exist_ok=True)
    fake_py = venv_bin / ("python.exe" if sys.platform == "win32" else "python")
    fake_py.write_text("#!/bin/sh\n")
    fake_py.chmod(0o755)

    py_bin = _resolve_venv_python(mock_workspace)
    assert str(fake_py.resolve()) == py_bin


@pytest.mark.asyncio
async def test_run_skill_script_blocks_traversal(mock_workspace: Path) -> None:
    tool = RunSkillScriptTool(workspace=mock_workspace)
    res = await tool.execute(
        MagicMock(),
        skill_name="../escape",
        script_name="test_script.py",
    )
    assert res.is_error
    assert "Path traversal" in str(res)

    res2 = await tool.execute(
        MagicMock(),
        skill_name="my_skill",
        script_name="../escape.py",
    )
    assert res2.is_error
    assert "Path traversal" in str(res2)


@pytest.mark.asyncio
async def test_run_skill_script_not_found(mock_workspace: Path) -> None:
    tool = RunSkillScriptTool(workspace=mock_workspace)
    res = await tool.execute(
        MagicMock(),
        skill_name="nonexistent_skill",
        script_name="test.py",
    )
    assert res.is_error
    assert "not found" in str(res).lower()


@pytest.mark.asyncio
async def test_run_skill_script_sandbox_bwrap(mock_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executed_commands: list[str] = []

    async def mock_create_subprocess_shell(cmd: str, **kwargs: Any) -> Any:
        executed_commands.append(cmd)
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = MagicMock(return_value=asyncio.sleep(0, result=(b"SANDBOX OK\n", b"")))
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_shell", mock_create_subprocess_shell)
    monkeypatch.setattr(sys, "platform", "linux")

    tool = RunSkillScriptTool(
        workspace=mock_workspace,
        sandbox="bwrap",
        sandbox_ro_binds=["/extra/ro"],
        sandbox_rw_binds=["/extra/rw"],
    )
    res = await tool.execute(
        MagicMock(),
        skill_name="my_skill",
        script_name="test_script.py",
        args=["foo"],
    )
    assert not res.is_error
    assert "SANDBOX OK" in str(res)
    assert len(executed_commands) == 1
    cmd = executed_commands[0]
    assert cmd.startswith("bwrap ")
    assert str(mock_workspace) in cmd
    assert "test_script.py" in cmd


def test_run_skill_script_create_inherits_exec_config(mock_workspace: Path) -> None:
    from nanobot.agent.tools.context import ToolContext
    from nanobot.agent.tools.shell import ExecToolConfig
    from nanobot.config.schema import ToolsConfig

    tools_cfg = ToolsConfig(
        exec=ExecToolConfig(
            sandbox="bwrap",
            sandbox_ro_binds=["/opt/bin"],
            sandbox_rw_binds=["/tmp/cache"],
        )
    )
    ctx = ToolContext(config=tools_cfg, workspace=str(mock_workspace))
    tool = RunSkillScriptTool.create(ctx)
    assert tool.sandbox == "bwrap"
    assert tool.sandbox_ro_binds == ["/opt/bin"]
    assert tool.sandbox_rw_binds == ["/tmp/cache"]

