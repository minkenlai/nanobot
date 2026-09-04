"""Unit tests for scripts/setup_web_widget.py."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.setup_web_widget import (
    _apply_caddyfile_update,
    _find_caddy_domain_block,
    _parse_existing_widget_js,
    _read_config_json,
    build_uploader_script,
    build_widget_js,
)


def test_build_widget_js_contains_expected_config() -> None:
    js = build_widget_js(
        domain="guide.example.com",
        title="Test Studio Guide",
        subtitle="Virtual Concierge",
        welcome="Hello and welcome!",
        chips=["Pricing", "Hours", "Location"],
        primary="#112233",
        accent="#445566",
    )

    assert "guide.example.com" in js
    assert "Test Studio Guide" in js
    assert "Virtual Concierge" in js
    assert "Hello and welcome!" in js
    assert '["Pricing", "Hours", "Location"]' in js
    assert "#112233" in js
    assert "#445566" in js

    # Verify presence of in-widget clear confirmation banner
    assert "sg-confirm-bar" in js
    assert "Clear chat history?" in js
    assert "sg-confirm-yes" in js
    assert "sg-confirm-no" in js


def test_parse_existing_widget_js_roundtrip(tmp_path: Path) -> None:
    widget_path = tmp_path / "widget.js"
    # Non-existent file returns empty dict
    assert _parse_existing_widget_js(widget_path) == {}

    original_chips = ["Services", "Contact", "FAQ"]
    js_content = build_widget_js(
        domain="chat.mybrand.org",
        title="My Brand Assistant",
        subtitle="Online Help",
        welcome="Welcome! How may I assist you today?",
        chips=original_chips,
        primary="#0a0a0a",
        accent="#2563eb",
    )
    widget_path.write_text(js_content, encoding="utf-8")

    parsed = _parse_existing_widget_js(widget_path)
    assert parsed.get("domain") == "chat.mybrand.org"
    assert parsed.get("studio_name") == "My Brand Assistant"
    assert parsed.get("subtitle") == "Online Help"
    assert parsed.get("welcome") == "Welcome! How may I assist you today?"
    assert parsed.get("quick_chips") == original_chips
    assert parsed.get("primary_color") == "#0a0a0a"
    assert parsed.get("accent_color") == "#2563eb"


def test_find_caddy_domain_block() -> None:
    caddy_content = """
site1.com {
    reverse_proxy 127.0.0.1:8001
}

chat.example.com {
    reverse_proxy 127.0.0.1:8900
    file_server
}

site2.com {
    respond "OK"
}
"""
    # Non-matching domain
    assert _find_caddy_domain_block(caddy_content, "notfound.com") is None

    # Matching domain
    span = _find_caddy_domain_block(caddy_content, "chat.example.com")
    assert span is not None
    start, end = span
    matched = caddy_content[start:end]
    assert "chat.example.com {" in matched
    assert "reverse_proxy 127.0.0.1:8900" in matched
    assert "site2.com" not in matched


def test_apply_caddyfile_update_new_file(tmp_path: Path) -> None:
    caddy_file = tmp_path / "Caddyfile"
    snippet = "guide.example.com {\n    reverse_proxy 127.0.0.1:8900\n}\n"

    _apply_caddyfile_update(caddy_file, "guide.example.com", snippet)

    assert caddy_file.exists()
    assert caddy_file.read_text(encoding="utf-8").strip() == snippet.strip()


def test_apply_caddyfile_update_already_up_to_date(tmp_path: Path) -> None:
    caddy_file = tmp_path / "Caddyfile"
    snippet = "guide.example.com {\n    reverse_proxy 127.0.0.1:8900\n}"
    caddy_file.write_text(snippet, encoding="utf-8")

    _apply_caddyfile_update(caddy_file, "guide.example.com", snippet)

    # No backup created since unchanged
    backups = list(tmp_path.glob("Caddyfile.bak.*"))
    assert len(backups) == 0


def test_apply_caddyfile_update_replaces_block_with_backup(tmp_path: Path) -> None:
    caddy_file = tmp_path / "Caddyfile"
    initial = (
        "other.com {\n    respond 200\n}\n\n"
        "guide.example.com {\n    reverse_proxy 127.0.0.1:8000\n}\n"
    )
    caddy_file.write_text(initial, encoding="utf-8")

    new_snippet = "guide.example.com {\n    reverse_proxy 127.0.0.1:8900\n    file_server\n}\n"
    _apply_caddyfile_update(caddy_file, "guide.example.com", new_snippet)

    # Backup should exist
    backups = list(tmp_path.glob("Caddyfile.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == initial

    # Content should have updated block while preserving other.com
    updated = caddy_file.read_text(encoding="utf-8")
    assert "other.com" in updated
    assert "reverse_proxy 127.0.0.1:8900" in updated
    assert "reverse_proxy 127.0.0.1:8000" not in updated


def test_apply_caddyfile_update_appends_when_domain_not_found(tmp_path: Path) -> None:
    caddy_file = tmp_path / "Caddyfile"
    initial = "other.com {\n    respond 200\n}\n"
    caddy_file.write_text(initial, encoding="utf-8")

    new_snippet = "guide.example.com {\n    reverse_proxy 127.0.0.1:8900\n}\n"
    _apply_caddyfile_update(caddy_file, "guide.example.com", new_snippet)

    backups = list(tmp_path.glob("Caddyfile.bak.*"))
    assert len(backups) == 1

    updated = caddy_file.read_text(encoding="utf-8")
    assert "other.com" in updated
    assert "guide.example.com" in updated


def test_read_config_json(tmp_path: Path) -> None:
    assert _read_config_json(None) == {}
    assert _read_config_json(str(tmp_path / "nonexistent.json")) == {}

    cfg_file = tmp_path / "config.json"
    data = {"api": {"port": 8900}, "name": "StudioBot"}
    cfg_file.write_text(json.dumps(data), encoding="utf-8")

    assert _read_config_json(str(cfg_file)) == data


def test_build_uploader_script() -> None:
    script = build_uploader_script(dest_dir="/var/www/assets", uploader_port=9999)
    assert "/var/www/assets" in script
    assert "9999" in script
    assert "class UploadHandler" in script
