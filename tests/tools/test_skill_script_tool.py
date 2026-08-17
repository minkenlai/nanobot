"""Tests for RunSkillScriptTool."""

from __future__ import annotations

import sys
from pathlib import Path
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
