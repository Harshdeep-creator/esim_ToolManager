"""Centralized logging for the Tool Manager."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

_CONFIGURED = False
_LOGGER_NAME = "esim_toolmanager"


def setup_logging(
    log_dir: Path,
    level: int = logging.INFO,
    console: bool = True,
    console_level: Optional[int] = None,
) -> logging.Logger:
    """Configure root tool-manager logger with rotating file + optional console."""
    global _CONFIGURED
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False  # avoid duplicate lines via root/basicConfig

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_dir / "tool_manager.log",
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(level)
    logger.addHandler(file_handler)

    if console:
        # Keep CLI tables readable; detailed INFO stays in the log file
        c_level = logging.WARNING if console_level is None else console_level
        if level <= logging.DEBUG:
            c_level = logging.DEBUG
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)
        console_handler.setLevel(c_level)
        logger.addHandler(console_handler)

    _CONFIGURED = True
    logger.debug("Logging initialized at %s", log_dir)
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a child logger; falls back to basicConfig if not yet configured."""
    if not _CONFIGURED:
        logging.basicConfig(level=logging.INFO)
    if name:
        return logging.getLogger(f"{_LOGGER_NAME}.{name}")
    return logging.getLogger(_LOGGER_NAME)
