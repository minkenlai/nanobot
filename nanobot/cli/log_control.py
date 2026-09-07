"""Runtime log visibility controls shared by CLI commands."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import Config, LoggingConfig

__all__ = ["_set_nanobot_logs", "configure_file_logging"]

_file_log_handler_id: int | None = None


def _set_nanobot_logs(enabled: bool) -> None:
    env_verbose = os.environ.get("NANOBOT_VERBOSE", "").strip().lower() in ("1", "true", "yes")
    if enabled or env_verbose:
        logger.enable("nanobot")
    else:
        logger.disable("nanobot")


def configure_file_logging(
    config: Config | None = None,
    *,
    log_dir: Path | None = None,
) -> int | None:
    """Configure rotating file sink for loguru from Config or defaults."""
    global _file_log_handler_id

    logging_cfg: LoggingConfig | None = getattr(config, "logging", None) if config is not None else None
    if logging_cfg is not None and not logging_cfg.enabled:
        if _file_log_handler_id is not None:
            logger.remove(_file_log_handler_id)
            _file_log_handler_id = None
        return None

    if _file_log_handler_id is not None:
        logger.remove(_file_log_handler_id)
        _file_log_handler_id = None

    env_log_file = os.environ.get("NANOBOT_LOG_FILE", "").strip()
    if env_log_file:
        log_path = Path(env_log_file).expanduser().resolve()
    elif logging_cfg is not None and logging_cfg.file:
        log_path = Path(logging_cfg.file).expanduser().resolve()
    else:
        from nanobot.config.paths import get_logs_dir

        target_dir = log_dir if log_dir is not None else get_logs_dir()
        log_path = target_dir / "nanobot.log"

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    env_level = os.environ.get("NANOBOT_LOG_LEVEL", "").strip()
    level = (env_level or (logging_cfg.level if logging_cfg else "INFO")).upper()
    rotation = logging_cfg.rotation if logging_cfg else "10 MB"
    retention = logging_cfg.retention if logging_cfg else "14 days"
    compression = logging_cfg.compression if logging_cfg else "gz"

    file_format = (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
        "{level: <5} | "
        "{extra[channel]} | "
        "{message}"
    )

    try:
        _file_log_handler_id = logger.add(
            str(log_path),
            format=file_format,
            level=level,
            rotation=rotation,
            retention=retention,
            compression=compression or None,
            colorize=False,
            enqueue=True,
            backtrace=True,
            diagnose=False,
            filter=lambda record: record["extra"].setdefault("channel", "-") or True,
        )
        return _file_log_handler_id
    except Exception as exc:
        logger.warning("Could not initialize file logging at {}: {}", log_path, exc)
        return None

