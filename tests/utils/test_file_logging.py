"""Tests for file logging and LoggingConfig."""

from pathlib import Path

from loguru import logger

from nanobot.cli.log_control import configure_file_logging
from nanobot.config.schema import Config, LoggingConfig


def test_logging_config_defaults() -> None:
    cfg = Config()
    assert cfg.logging.enabled is True
    assert cfg.logging.level == "INFO"
    assert cfg.logging.file is None
    assert cfg.logging.rotation == "10 MB"
    assert cfg.logging.retention == "14 days"


def test_logging_config_custom() -> None:
    cfg = Config(
        logging=LoggingConfig(
            enabled=False,
            level="DEBUG",
            file="/custom/path.log",
            rotation="50 MB",
            retention="30 days",
        )
    )
    assert cfg.logging.enabled is False
    assert cfg.logging.level == "DEBUG"
    assert cfg.logging.file == "/custom/path.log"
    assert cfg.logging.rotation == "50 MB"
    assert cfg.logging.retention == "30 days"


def test_configure_file_logging_creates_and_writes_file(tmp_path: Path) -> None:
    log_file = tmp_path / "test.log"
    cfg = Config(logging=LoggingConfig(enabled=True, file=str(log_file), level="DEBUG"))

    handler_id = configure_file_logging(cfg)
    assert handler_id is not None

    logger.info("Test log line 12345")
    logger.debug("Debug log line 67890")

    logger.complete()

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Test log line 12345" in content
    assert "Debug log line 67890" in content


def test_configure_file_logging_disabled_removes_handler(tmp_path: Path) -> None:
    log_file = tmp_path / "test_disabled.log"
    cfg = Config(logging=LoggingConfig(enabled=False, file=str(log_file)))

    handler_id = configure_file_logging(cfg)
    assert handler_id is None

    logger.info("Should not be written")
    logger.complete()

    assert not log_file.exists()


def test_configure_file_logging_env_overrides(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / "env_override.log"
    monkeypatch.setenv("NANOBOT_LOG_FILE", str(env_file))
    monkeypatch.setenv("NANOBOT_LOG_LEVEL", "WARNING")

    cfg = Config(logging=LoggingConfig(enabled=True, file=str(tmp_path / "ignored.log"), level="DEBUG"))
    handler_id = configure_file_logging(cfg)
    assert handler_id is not None

    logger.info("Info message - should not be in WARNING log")
    logger.warning("Warning message - should be logged")
    logger.complete()

    assert env_file.exists()
    assert not (tmp_path / "ignored.log").exists()
    content = env_file.read_text(encoding="utf-8")
    assert "Info message" not in content
    assert "Warning message - should be logged" in content


def test_configure_file_logging_default_dir(tmp_path: Path) -> None:
    cfg = Config(logging=LoggingConfig(enabled=True, file=None))
    handler_id = configure_file_logging(cfg, log_dir=tmp_path)
    assert handler_id is not None

    expected_file = tmp_path / "nanobot.log"
    logger.info("Default dir log message")
    logger.complete()

    assert expected_file.exists()
    assert "Default dir log message" in expected_file.read_text(encoding="utf-8")

