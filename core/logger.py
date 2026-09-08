"""Logging configuration for PadPilot."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

LOG_DIR = Path.home() / "Library" / "Logs" / "PadPilot"
LOG_FILE = LOG_DIR / "padpilot.log"

_configured = False


def get_log_file_path() -> Path:
    return LOG_FILE


def setup_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return

    root_logger = logging.getLogger("PadPilot")
    root_logger.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        # Rotating file handler (5MB, 3 backups)
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except (PermissionError, OSError):
        pass

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    _configured = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    setup_logging()
    if name:
        return logging.getLogger(f"PadPilot.{name}")
    return logging.getLogger("PadPilot")
