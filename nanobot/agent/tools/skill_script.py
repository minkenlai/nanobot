"""Tool for safely executing pre-approved skill scripts."""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

from loguru import logger

from nanobot.agent.skills import BUILTIN_SKILLS_DIR, SkillsLoader
from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.schema import ArraySchema, StringSchema, tool_parameters_schema
from nanobot.config.paths import get_workspace_path


def _resolve_venv_python(workspace: Path) -> str:
    """Resolve python interpreter path, preferring <workspace>/.venv if present."""
    if sys.platform == "win32":
        venv_py = workspace / ".venv" / "Scripts" / "python.exe"
    else:
        venv_py = workspace / ".venv" / "bin" / "python"

    if venv_py.exists() and os.access(venv_py, os.X_OK if sys.platform != "win32" else os.R_OK):
        return str(venv_py.resolve())
    return sys.executable


@tool_parameters(
    tool_parameters_schema(
        skill_name=StringSchema(
            "Name of the skill whose script should be run (e.g. 'github', 'daily-sync')."
        ),
        script_name=StringSchema(
            "Name of the Python script inside the skill's scripts/ directory (e.g. 'run.py', 'sync.py')."
        ),
        args=ArraySchema(
            items=StringSchema("Command-line argument passed to the script."),
            description="Optional list of string arguments passed to the script.",
        ),
        required=["skill_name", "script_name"],
    )
)
class RunSkillScriptTool(Tool):
    """Tool for safely executing pre-approved Python scripts from skills."""

    @property
    def name(self) -> str:
        return "run_skill_script"

    @property
    def description(self) -> str:
        return (
            "Safely execute a pre-approved Python script located in an enabled skill's scripts/ directory. "
            "Runs within the workspace's virtual environment (.venv) if present. "
            "Use this instead of generic exec to run skill-specific automation scripts."
        )

    def __init__(
        self,
        workspace: Path | None = None,
        timeout: float = 120.0,
        sandbox: str = "",
        sandbox_ro_binds: list[str] | None = None,
        sandbox_rw_binds: list[str] | None = None,
    ) -> None:
        self._workspace = workspace
        self._timeout = timeout
        self.sandbox = sandbox
        self.sandbox_ro_binds = list(sandbox_ro_binds or [])
        self.sandbox_rw_binds = list(sandbox_rw_binds or [])

    @classmethod
    def create(cls, ctx: ToolContext) -> RunSkillScriptTool:
        ws = Path(ctx.workspace).expanduser() if ctx.workspace else get_workspace_path()
        exec_cfg = getattr(ctx.config, "exec", None)
        return cls(
            workspace=ws,
            sandbox=getattr(exec_cfg, "sandbox", "") or "",
            sandbox_ro_binds=list(getattr(exec_cfg, "sandbox_ro_binds", []) or []),
            sandbox_rw_binds=list(getattr(exec_cfg, "sandbox_rw_binds", []) or []),
        )

    def _find_skill_script(self, workspace: Path, skill_name: str, script_name: str) -> Path | None:
        """Locate the script and ensure it is strictly contained in the skill's scripts/ dir."""
        loader = SkillsLoader(workspace=workspace)
        skills = loader.list_skills(filter_unavailable=False)
        skill_entry = next((s for s in skills if s["name"] == skill_name), None)

        candidates: list[Path] = []
        if skill_entry:
            skill_dir = Path(skill_entry["path"]).parent
            candidates.append(skill_dir / "scripts" / script_name)

        candidates.extend([
            workspace / "skills" / skill_name / "scripts" / script_name,
            BUILTIN_SKILLS_DIR / skill_name / "scripts" / script_name,
        ])

        for cand in candidates:
            cand_resolved = cand.resolve()
            scripts_dir = cand.parent.resolve()
            if cand_resolved.exists() and cand_resolved.is_file() and cand_resolved.is_relative_to(scripts_dir):
                return cand_resolved
        return None

    async def execute(self, *args: Any, **kwargs: Any) -> ToolResult:
        ctx = args[0] if args and isinstance(args[0], ToolContext) else getattr(self, "context", None)
        ws = self._workspace
        if not ws and ctx and hasattr(ctx, "workspace") and ctx.workspace:
            ws = Path(ctx.workspace).expanduser()
        if not ws:
            ws = get_workspace_path()

        skill_name = str(kwargs.get("skill_name", "")).strip()
        script_name = str(kwargs.get("script_name", "")).strip()
        raw_args: object = kwargs.get("args")
        script_args: list[str] = []
        if isinstance(raw_args, (list, tuple)):
            for item in cast(list[object], raw_args):
                script_args.append(str(item))

        if not skill_name or not script_name:
            return ToolResult.error("Both skill_name and script_name are required.")

        # Prevent basic path traversal injection in parameters
        if ".." in skill_name or "/" in skill_name or "\\" in skill_name:
            return ToolResult.error(f"Invalid skill_name '{skill_name}'. Path traversal characters not allowed.")
        if ".." in script_name or "/" in script_name or "\\" in script_name:
            return ToolResult.error(f"Invalid script_name '{script_name}'. Path traversal characters not allowed.")

        script_path = self._find_skill_script(ws, skill_name, script_name)
        if not script_path:
            return ToolResult.error(
                f"Script '{script_name}' not found for skill '{skill_name}'. "
                f"Ensure the script exists in the skill's scripts/ directory."
            )

        python_bin = _resolve_venv_python(ws)
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        venv_dir = ws / ".venv"
        if venv_dir.exists() and venv_dir.is_dir():
            env["VIRTUAL_ENV"] = str(venv_dir.resolve())
            bin_dir = venv_dir / ("Scripts" if sys.platform == "win32" else "bin")
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

        sandbox = self.sandbox
        sandbox_ro_binds = list(self.sandbox_ro_binds)
        sandbox_rw_binds = list(self.sandbox_rw_binds)
        if not sandbox and ctx and hasattr(ctx, "config") and hasattr(ctx.config, "exec"):
            exec_cfg = ctx.config.exec
            if exec_cfg:
                sandbox = getattr(exec_cfg, "sandbox", "") or ""
                sandbox_ro_binds = list(getattr(exec_cfg, "sandbox_ro_binds", []) or [])
                sandbox_rw_binds = list(getattr(exec_cfg, "sandbox_rw_binds", []) or [])

        cmd = [python_bin, str(script_path), *script_args]
        is_windows = sys.platform == "win32"
        try:
            if sandbox and not is_windows:
                from nanobot.agent.tools.sandbox import wrap_command

                ro_binds = list(sandbox_ro_binds)
                with suppress(Exception):
                    builtin_resolved = BUILTIN_SKILLS_DIR.resolve()
                    if builtin_resolved.exists() and str(builtin_resolved) not in ro_binds:
                        ro_binds.append(str(builtin_resolved))
                with suppress(Exception):
                    py_path = Path(python_bin).resolve()
                    if py_path.exists():
                        try:
                            py_path.relative_to(ws.resolve())
                        except ValueError:
                            try:
                                py_path.relative_to(Path("/usr"))
                            except ValueError:
                                py_dir = str(py_path.parent)
                                if py_dir not in ro_binds:
                                    ro_binds.append(py_dir)

                raw_cmd = shlex.join(cmd)
                wrapped_cmd = wrap_command(
                    sandbox,
                    raw_cmd,
                    str(ws),
                    str(ws),
                    sandbox_ro_binds=ro_binds,
                    sandbox_rw_binds=sandbox_rw_binds,
                )
                proc = await asyncio.create_subprocess_shell(
                    wrapped_cmd,
                    cwd=str(ws),
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            else:
                if sandbox and is_windows:
                    logger.warning(
                        "Sandbox '{}' is not supported on Windows; running unsandboxed",
                        sandbox,
                    )
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(ws),
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            try:
                stdout_data, stderr_data = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self._timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult.error(f"Skill script '{script_name}' timed out after {self._timeout}s.")

            stdout_str = stdout_data.decode("utf-8", errors="replace").strip()
            stderr_str = stderr_data.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0:
                err_msg = stderr_str or stdout_str or f"Process exited with code {proc.returncode}"
                return ToolResult.error(
                    f"Skill script '{script_name}' failed (code {proc.returncode}):\n{err_msg}"
                )

            output = stdout_str
            if stderr_str:
                output = f"{output}\n[stderr]: {stderr_str}" if output else stderr_str
            return ToolResult(
                output or f"Skill script '{script_name}' executed successfully with no output.",
                stdout=stdout_str,
                stderr=stderr_str,
            )
        except Exception as e:
            logger.warning("Failed to execute skill script: {}", e)
            return ToolResult.error(f"Failed to execute skill script: {e}")
