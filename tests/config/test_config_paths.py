import os
from pathlib import Path

from nanobot.config.paths import (
    get_bridge_install_dir,
    get_cli_history_path,
    get_cron_dir,
    get_data_dir,
    get_legacy_sessions_dir,
    get_logs_dir,
    get_media_dir,
    get_runtime_subdir,
    get_workspace_path,
    is_default_workspace,
)


def test_runtime_dirs_follow_config_path(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "instance-a"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)

    assert get_data_dir() == config_dir
    assert get_cron_dir() == config_dir / "cron"
    assert get_logs_dir() == config_dir / "logs"


def test_get_data_dir_fallback_on_read_only(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "readonly-instance"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)

    # Simulate read-only directory
    original_access = os.access

    def mock_access(path, mode):
        if str(path) == str(config_dir) and mode == os.W_OK:
            return False
        return original_access(path, mode)

    monkeypatch.setattr(os, "access", mock_access)
    # Mock ensure_dir to avoid creating ~/.nanobot in restricted test env
    monkeypatch.setattr("nanobot.config.paths.ensure_dir", lambda p: p)

    assert get_data_dir() == Path.home() / ".nanobot"


def test_media_dir_supports_channel_namespace(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "instance-b"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)

    assert get_media_dir() == config_dir / "media"
    assert get_media_dir("telegram") == config_dir / "media" / "telegram"


def test_shared_and_legacy_paths_remain_global() -> None:
    assert get_cli_history_path() == Path.home() / ".nanobot" / "history" / "cli_history"
    assert get_bridge_install_dir() == Path.home() / ".nanobot" / "bridge"
    assert get_legacy_sessions_dir() == Path.home() / ".nanobot" / "sessions"


def test_workspace_path_is_explicitly_resolved(monkeypatch) -> None:
    # Mock ensure_dir to avoid real mkdir in restricted env
    monkeypatch.setattr("nanobot.config.paths.ensure_dir", lambda p: p)

    assert get_workspace_path() == Path.home() / ".nanobot" / "workspace"
    assert get_workspace_path("~/custom-workspace") == Path.home() / "custom-workspace"


def test_is_default_workspace_distinguishes_default_and_custom_paths() -> None:
    assert is_default_workspace(None) is True
    assert is_default_workspace(Path.home() / ".nanobot" / "workspace") is True
    assert is_default_workspace("~/custom-workspace") is False
