"""Logging configuration for SidecarSwitch."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional
from core.storage import private_directory, private_file

LOG_DIR = Path.home() / "Library" / "Logs" / "SidecarSwitch"
LOG_FILE = LOG_DIR / "sidecarswitch.log"

_configured = False


class PrivateRotatingFileHandler(RotatingFileHandler):
    def _open(self):
        private_file(Path(self.baseFilename), create=True)
        return super()._open()


def get_log_file_path() -> Path:
    return LOG_FILE


def setup_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return

    root_logger = logging.getLogger("SidecarSwitch")
    root_logger.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        private_directory(LOG_DIR)
        for path in (LOG_FILE, *(LOG_DIR / f'sidecarswitch.log.{n}' for n in range(1, 4))):
            private_file(path, create=path == LOG_FILE)
        # Rotating file handler (5MB, 3 backups)
        file_handler = PrivateRotatingFileHandler(
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
        return logging.getLogger(f"SidecarSwitch.{name}")
    return logging.getLogger("SidecarSwitch")
