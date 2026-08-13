"""Runtime log visibility controls shared by CLI commands."""

import os

from loguru import logger

__all__ = ["_set_nanobot_logs"]


def _set_nanobot_logs(enabled: bool) -> None:
    env_verbose = os.environ.get("NANOBOT_VERBOSE", "").strip().lower() in ("1", "true", "yes")
    if enabled or env_verbose:
        logger.enable("nanobot")
    else:
        logger.disable("nanobot")
