"""Tool for managing WhatsApp staff numbers and allowed senders in config.json."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, cast

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema
from nanobot.config.paths import get_config_path


def normalize_number(raw: str) -> str:
    """Normalize phone number or WhatsApp JID."""
    val = raw.strip()
    if not val:
        return ""
    if "@" in val:
        return val
    cleaned = re.sub(r"[\s\-\(\)]", "", val)
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    return cleaned


@tool_parameters(
    tool_parameters_schema(
        action=StringSchema(
            "Action to perform: 'add' (add staff number), 'remove' (remove staff number), or 'list' (list current staff numbers)."
        ),
        number=StringSchema(
            "WhatsApp phone number or user ID (e.g. '+13105551234' or '13105551234'). Required for 'add' and 'remove'."
        ),
        required=["action"],
    )
)
class WhatsAppStaffTool(Tool):
    """Tool for managing WhatsApp staff numbers and allowed senders in config.json."""

    @property
    def name(self) -> str:
        return "whatsapp_staff"

    @property
    def description(self) -> str:
        return (
            "Add, remove, or list WhatsApp staff numbers and allowed senders in nanobot config.json. "
            "Use when managing WhatsApp channel staff routing or permissions."
        )

    def __init__(self, config_path: Path | str | None = None) -> None:
        self.config_path = Path(config_path) if config_path else get_config_path()

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        channels_obj: Any = getattr(ctx.config, "channels", None)
        raw_whatsapp: Any = None
        if isinstance(channels_obj, dict):
            channels_dict = cast(dict[str, Any], channels_obj)
            raw_whatsapp = channels_dict.get("whatsapp")
        elif channels_obj is not None:
            raw_whatsapp = getattr(channels_obj, "whatsapp", None)

        if not raw_whatsapp:
            return False
        if isinstance(raw_whatsapp, dict):
            wa_dict = cast(dict[str, Any], raw_whatsapp)
            return bool(wa_dict.get("enabled", True))
        return bool(getattr(raw_whatsapp, "enabled", True))

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls()

    async def execute(
        self,
        action: str = "",
        number: str = "",
        **_kwargs: Any,
    ) -> ToolResult:
        act = action.strip().lower()
        if act not in ("add", "remove", "list"):
            return ToolResult.error("Action must be 'add', 'remove', or 'list'")

        config_path = self.config_path
        if not config_path.exists():
            return ToolResult.error(f"Config file not found at {config_path}")

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return ToolResult.error(f"Error reading {config_path}: {e}")

        if not isinstance(data, dict):
            return ToolResult.error(f"Top level of {config_path} must be a JSON object")

        data_dict: dict[str, Any] = cast(dict[str, Any], data)
        raw_channels = data_dict.get("channels")
        channels: dict[str, Any] = cast(dict[str, Any], raw_channels) if isinstance(raw_channels, dict) else {}
        data_dict["channels"] = channels

        raw_whatsapp = channels.get("whatsapp")
        whatsapp: dict[str, Any] = cast(dict[str, Any], raw_whatsapp) if isinstance(raw_whatsapp, dict) else {}
        channels["whatsapp"] = whatsapp

        allow_from_key = "allow_from" if "allow_from" in whatsapp or "allowFrom" not in whatsapp else "allowFrom"
        raw_allow = whatsapp.get(allow_from_key)
        allow_from: list[str] = [str(x) for x in cast(list[Any], raw_allow)] if isinstance(raw_allow, list) else []
        whatsapp[allow_from_key] = allow_from

        raw_routing = whatsapp.get("routing")
        routing: dict[str, Any] = cast(dict[str, Any], raw_routing) if isinstance(raw_routing, dict) else {}
        whatsapp["routing"] = routing

        staff_key = "staff_numbers" if "staff_numbers" in routing or "staffNumbers" not in routing else "staffNumbers"
        raw_staff = routing.get(staff_key)
        staff_numbers: list[str] = [str(x) for x in cast(list[Any], raw_staff)] if isinstance(raw_staff, list) else []
        routing[staff_key] = staff_numbers

        if act == "list":
            summary = (
                "Current WhatsApp Configuration:\n"
                f"  Channel Enabled : {whatsapp.get('enabled', False)}\n"
                f"  Allow List      : {allow_from}\n"
                f"  Routing Enabled : {routing.get('enabled', True)}\n"
                f"  Staff Numbers   : {staff_numbers}\n"
                f"  Guide URL       : {routing.get('guide_instance_url', 'http://127.0.0.1:18791/v1/chat/completions')}"
            )
            return ToolResult(summary)

        norm = normalize_number(number)
        if not norm:
            return ToolResult.error(f"A valid WhatsApp phone number or ID is required for action '{act}'")

        if act == "remove":
            removed = False
            for n in (number.strip(), norm, f"+{norm}"):
                if n in allow_from and "*" not in allow_from:
                    allow_from.remove(n)
                    removed = True
                if n in staff_numbers:
                    staff_numbers.remove(n)
                    removed = True

            if not removed:
                return ToolResult(f"Number '{number}' was not found in staff list.")

            out_msg = f"Removed '{number}' from WhatsApp staff numbers and allow list."

        else:  # add
            whatsapp["enabled"] = True
            routing["enabled"] = True

            if norm not in staff_numbers and f"+{norm}" not in staff_numbers:
                staff_numbers.append(norm)

            if "*" not in allow_from and norm not in allow_from and f"+{norm}" not in allow_from:
                allow_from.append(norm)

            out_msg = f"Successfully added WhatsApp staff number: {norm}"

        # Create backup before saving modification
        backup_path = config_path.with_name(f"{config_path.name}.bak")
        try:
            shutil.copy2(config_path, backup_path)
        except Exception as e:
            out_msg += f"\nNote: Failed to create backup at {backup_path}: {e}"

        # Atomic write
        temp_dir = config_path.parent
        temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=temp_dir, delete=False, encoding="utf-8") as tf:
            json.dump(data, tf, indent=2, ensure_ascii=False)
            tf.write("\n")
            temp_name = tf.name

        os.replace(temp_name, config_path)
        out_msg += f"\nSaved backup to {backup_path}\nUpdated config file at {config_path}\nStaff Numbers: {staff_numbers}"
        return ToolResult(out_msg)
