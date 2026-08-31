"""Staff access policy manager for commands, tools, and skills on the Admin Node."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.config.schema import StaffPolicyConfig


class StaffPolicy:
    """Policy manager enforcing allowed/disabled commands, tools, and skills."""

    def __init__(
        self,
        enabled: bool = False,
        unrestricted_users: list[str] | None = None,
        allowed_commands: list[str] | None = None,
        disabled_commands: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        disabled_tools: list[str] | None = None,
        allowed_skills: list[str] | None = None,
        disabled_skills: list[str] | None = None,
    ) -> None:
        self.enabled = enabled
        self.unrestricted_users = list(unrestricted_users or [])
        self.allowed_commands = list(allowed_commands) if allowed_commands is not None else None
        self.disabled_commands = list(disabled_commands or [])
        self.allowed_tools = list(allowed_tools) if allowed_tools is not None else None
        self.disabled_tools = list(disabled_tools or [])
        self.allowed_skills = list(allowed_skills) if allowed_skills is not None else None
        self.disabled_skills = list(disabled_skills or [])

    @classmethod
    def from_config(cls, cfg: StaffPolicyConfig | None) -> StaffPolicy:
        if cfg is None:
            return cls(enabled=False)
        return cls(
            enabled=cfg.enabled,
            unrestricted_users=cfg.unrestricted_users,
            allowed_commands=cfg.allowed_commands,
            disabled_commands=cfg.disabled_commands,
            allowed_tools=cfg.allowed_tools,
            disabled_tools=cfg.disabled_tools,
            allowed_skills=cfg.allowed_skills,
            disabled_skills=cfg.disabled_skills,
        )

    def is_unrestricted(self, sender_id: str | None, channel: str | None = None) -> bool:
        """Return True if *sender_id* is in *unrestricted_users* or if policy is disabled."""
        if not self.enabled:
            return True
        if not self.unrestricted_users:
            return False

        clean_sender = str(sender_id or "").strip()
        if not clean_sender:
            return False

        candidates: set[str] = set()

        chan_prefix = channel or ""
        val = clean_sender
        if ":" in clean_sender and not clean_sender.startswith("+"):
            parts = clean_sender.split(":", 1)
            chan_prefix = parts[0]
            val = parts[1]

        candidates.add(clean_sender)
        candidates.add(val)

        if "|" in val:
            u_id, u_name = val.split("|", 1)
            u_id = u_id.strip()
            u_name = u_name.strip().lstrip("@")
            candidates.add(u_id)
            if u_name:
                candidates.add(u_name)
                candidates.add(f"@{u_name}")

        if "@s.whatsapp.net" in val:
            phone_part = val.split("@")[0]
            candidates.add(phone_part)

        base_vals = list(candidates)
        for v in base_vals:
            clean_v = v.split(":", 1)[-1] if ":" in v and not v.startswith("+") else v
            if clean_v.startswith("+") and clean_v[1:].isdigit():
                candidates.add(clean_v[1:])
            elif clean_v.isdigit():
                candidates.add(f"+{clean_v}")

        if chan_prefix:
            base_candidates = list(candidates)
            for c in base_candidates:
                if not c.startswith(f"{chan_prefix}:"):
                    candidates.add(f"{chan_prefix}:{c}")

        for user in self.unrestricted_users:
            clean_user = str(user or "").strip()
            clean_user_val = clean_user.split(":", 1)[-1] if ":" in clean_user and not clean_user.startswith("+") else clean_user
            clean_user_val = clean_user_val.lstrip("@")
            if clean_user in candidates or clean_user_val in candidates or f"@{clean_user_val}" in candidates or f"+{clean_user_val}" in candidates:
                return True

        return False

    def is_command_allowed(self, sender_id: str | None, channel: str | None, raw_command: str) -> bool:
        """Return True if the slash command is permitted for this sender."""
        if self.is_unrestricted(sender_id, channel):
            return True

        raw = (raw_command or "").strip()
        if not raw.startswith("/"):
            return True

        cmd = raw.split()[0].lower()
        if "@" in cmd:
            cmd = cmd.split("@")[0]

        if self.disabled_commands and (cmd in self.disabled_commands or cmd.lstrip("/") in self.disabled_commands):
            return False

        if self.allowed_commands is not None and "*" not in self.allowed_commands:
            allowed_set = {c.lower() for c in self.allowed_commands}
            return cmd in allowed_set or cmd.lstrip("/") in allowed_set

        return True

    def filter_tools(
        self,
        sender_id: str | None,
        channel: str | None,
        base_tools: ToolRegistry,
    ) -> ToolRegistry:
        """Return a ToolRegistry containing only tools permitted for this sender."""
        if self.is_unrestricted(sender_id, channel):
            return base_tools
        return base_tools.filter(
            allowed_tools=self.allowed_tools,
            disabled_tools=self.disabled_tools,
        )

    def filter_disabled_skills(
        self,
        sender_id: str | None,
        channel: str | None,
        base_disabled: list[str] | set[str] | None,
        all_skills: list[dict[str, str]] | None = None,
    ) -> set[str]:
        """Return the combined set of disabled skill names for this sender."""
        base_set = set(base_disabled or [])
        if self.is_unrestricted(sender_id, channel):
            return base_set

        combined = base_set | set(self.disabled_skills)
        if self.allowed_skills is not None and "*" not in self.allowed_skills:
            allowed_set = set(self.allowed_skills)
            if all_skills:
                for s in all_skills:
                    name = s.get("name", "")
                    if name and name not in allowed_set:
                        combined.add(name)
        return combined

    def validate_policy(
        self,
        registered_tools: set[str] | None = None,
        registered_commands: set[str] | None = None,
        registered_skills: set[str] | None = None,
    ) -> list[str]:
        """Validate configured tools, commands, and skills against registered items and return warnings."""
        warnings: list[str] = []
        if not self.enabled:
            return warnings

        if registered_tools:
            for item in (self.allowed_tools or []):
                clean_name = item[4:] if item.startswith("mcp_") else item
                if item != "*" and clean_name not in registered_tools and item not in registered_tools:
                    warnings.append(f"[StaffPolicy Warning] Unrecognized tool '{item}' in allowedTools.")
            for item in self.disabled_tools:
                clean_name = item[4:] if item.startswith("mcp_") else item
                if item != "*" and clean_name not in registered_tools and item not in registered_tools:
                    warnings.append(f"[StaffPolicy Warning] Unrecognized tool '{item}' in disabledTools.")

        if registered_commands:
            valid_cmds = {c.lower() for c in registered_commands}
            valid_cmds.update({c.lstrip("/").lower() for c in registered_commands})
            for item in (self.allowed_commands or []):
                norm = item.strip().lower()
                if norm != "*" and norm not in valid_cmds and norm.lstrip("/") not in valid_cmds:
                    warnings.append(f"[StaffPolicy Warning] Unrecognized command '{item}' in allowedCommands.")
            for item in self.disabled_commands:
                norm = item.strip().lower()
                if norm != "*" and norm not in valid_cmds and norm.lstrip("/") not in valid_cmds:
                    warnings.append(f"[StaffPolicy Warning] Unrecognized command '{item}' in disabledCommands.")

        if registered_skills:
            for item in (self.allowed_skills or []):
                if item != "*" and item not in registered_skills:
                    warnings.append(f"[StaffPolicy Warning] Unrecognized skill '{item}' in allowedSkills.")
            for item in self.disabled_skills:
                if item != "*" and item not in registered_skills:
                    warnings.append(f"[StaffPolicy Warning] Unrecognized skill '{item}' in disabledSkills.")

        return warnings
