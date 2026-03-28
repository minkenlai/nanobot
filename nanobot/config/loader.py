"""Configuration loading utilities."""

import json
import os
from pathlib import Path

import pydantic
from loguru import logger

from nanobot.config.schema import Config

# Global variable to store current config path (for multi-instance support)
_current_config_path: Path | None = None

# Global variable to store overlay config path
_current_overlay_path: Path | None = None


def set_overlay_path(path: Path) -> None:
    """Set the current config overlay path."""
    global _current_overlay_path
    _current_overlay_path = path


def get_overlay_path() -> Path | None:
    """Get the config overlay path, checking global state then env var."""
    if _current_overlay_path:
        return _current_overlay_path
    env = os.environ.get("NANOBOT_CONFIG_OVERLAY")
    if env:
        return Path(env).expanduser()
    return None


def apply_overlay(base: dict, overlay_path: Path) -> dict:
    """
    Merge overlay JSON into base config at the section (top-level key) level.
    Overlay sections replace base sections wholesale — no deep merge.
    """
    if not overlay_path.exists():
        logger.warning(f"Config overlay not found: {overlay_path} — skipping.")
        return base
    try:
        with open(overlay_path, encoding="utf-8") as f:
            overlay = json.load(f)
        logger.info(f"Applying config overlay from {overlay_path} (sections: {list(overlay.keys())})")
        base.update(overlay)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load config overlay from {overlay_path}: {e} — skipping.")
    return base


def set_config_path(path: Path) -> None:
    """Set the current config path (used to derive data directory)."""
    global _current_config_path
    _current_config_path = path


def get_config_path() -> Path:
    """Get the configuration file path."""
    if _current_config_path:
        return _current_config_path
    return Path.home() / ".nanobot" / "config.json"


def load_config(config_path: Path | None = None) -> Config:
    """
    Load configuration from file or create default.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Loaded configuration object.
    """
    path = config_path or get_config_path()

    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data = _migrate_config(data)
            overlay_path = get_overlay_path()
            if overlay_path:
                data = apply_overlay(data, overlay_path)
            return Config.model_validate(data)
        except (json.JSONDecodeError, ValueError, pydantic.ValidationError) as e:
            logger.warning(f"Failed to load config from {path}: {e}")
            logger.warning("Using default configuration.")

    return Config()


def save_config(config: Config, config_path: Path | None = None) -> None:
    """
    Save configuration to file.

    Args:
        config: Configuration to save.
        config_path: Optional path to save to. Uses default if not provided.
    """
    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(mode="json", by_alias=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _migrate_config(data: dict) -> dict:
    """Migrate old config formats to current."""
    # Move tools.exec.restrictToWorkspace → tools.restrictToWorkspace
    tools = data.get("tools", {})
    exec_cfg = tools.get("exec", {})
    if "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")
    return data
