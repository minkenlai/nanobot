"""Tests for WhatsAppStaffTool."""

import json
from pathlib import Path

import pytest

from nanobot.agent.tools.whatsapp_staff import WhatsAppStaffTool


@pytest.mark.asyncio
async def test_whatsapp_staff_tool_add_number(tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    backup_file = tmp_path / "config.json.bak"
    initial_data = {
        "channels": {
            "whatsapp": {
                "enabled": False,
                "allow_from": [],
                "routing": {
                    "enabled": False,
                    "staff_numbers": [],
                },
            }
        }
    }
    config_file.write_text(json.dumps(initial_data, indent=2), encoding="utf-8")

    tool = WhatsAppStaffTool(config_path=config_file)
    result = await tool.execute(action="add", number="+13105551234")

    assert not result.is_error
    assert "Successfully added WhatsApp staff number: 13105551234" in str(result)
    assert backup_file.exists()

    updated = json.loads(config_file.read_text(encoding="utf-8"))
    whatsapp = updated["channels"]["whatsapp"]
    assert whatsapp["enabled"] is True
    assert whatsapp["routing"]["enabled"] is True
    assert "13105551234" in whatsapp["allow_from"]
    assert "13105551234" in whatsapp["routing"]["staff_numbers"]


@pytest.mark.asyncio
async def test_whatsapp_staff_tool_list(tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    initial_data = {
        "channels": {
            "whatsapp": {
                "enabled": True,
                "allow_from": ["13105551234"],
                "routing": {
                    "enabled": True,
                    "staff_numbers": ["13105551234"],
                },
            }
        }
    }
    config_file.write_text(json.dumps(initial_data, indent=2), encoding="utf-8")

    tool = WhatsAppStaffTool(config_path=config_file)
    result = await tool.execute(action="list")

    assert not result.is_error
    assert "13105551234" in str(result)


@pytest.mark.asyncio
async def test_whatsapp_staff_tool_remove(tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    initial_data = {
        "channels": {
            "whatsapp": {
                "enabled": True,
                "allow_from": ["13105551234"],
                "routing": {
                    "enabled": True,
                    "staff_numbers": ["13105551234"],
                },
            }
        }
    }
    config_file.write_text(json.dumps(initial_data, indent=2), encoding="utf-8")

    tool = WhatsAppStaffTool(config_path=config_file)
    result = await tool.execute(action="remove", number="13105551234")

    assert not result.is_error
    assert "Removed '13105551234'" in str(result)

    updated = json.loads(config_file.read_text(encoding="utf-8"))
    whatsapp = updated["channels"]["whatsapp"]
    assert "13105551234" not in whatsapp["allow_from"]


def test_whatsapp_staff_enabled_toggle() -> None:
    from unittest.mock import MagicMock

    ctx = MagicMock()
    ctx.config.channels.whatsapp.enabled = True
    assert WhatsAppStaffTool.enabled(ctx) is True

    ctx.config.channels.whatsapp.enabled = False
    assert WhatsAppStaffTool.enabled(ctx) is False
