"""Notification utility for PadPilot.

Per requirements:
Normal operations do NOT trigger notifications.
Only abnormal conditions (failures, errors, cooldowns) send notifications.
"""

from __future__ import annotations

import subprocess
from typing import Optional

from core.logger import get_logger

logger = get_logger("Notifier")


def notify_error(message: str, subtitle: Optional[str] = None) -> None:
    """Send an error/warning notification to macOS Notification Center."""
    try:
        sub_clause = f'subtitle "{subtitle}"' if subtitle else ""
        script = f'display notification "{message}" with title "PadPilot" {sub_clause} sound name "Basso"'
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
            check=False,
        )
        logger.info(f"Notification sent: {message} ({subtitle})")
    except Exception as e:
        logger.warning(f"Failed to post macOS notification: {e}")
