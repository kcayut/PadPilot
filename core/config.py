"""Configuration and runtime state persistence for PadPilot."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from core.logger import get_logger
from core.models import (
    DEFAULT_VIRTUAL_DISPLAY_NAME,
    SWIFTBAR_PLUGIN_ID,
    IpadConfig,
    OperationMode,
    StatusSnapshot,
)

logger = get_logger("Config")

APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "PadPilot"
CONFIG_FILE = APP_SUPPORT_DIR / "config.json"
RUNTIME_DIR = APP_SUPPORT_DIR / "runtime"
STATUS_FILE = RUNTIME_DIR / "status.json"

try:
    APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
except (PermissionError, OSError):
    APP_SUPPORT_DIR = Path("/tmp/PadPilot")
    CONFIG_FILE = APP_SUPPORT_DIR / "config.json"
    RUNTIME_DIR = APP_SUPPORT_DIR / "runtime"
    STATUS_FILE = RUNTIME_DIR / "status.json"
    APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Config:
    mode: OperationMode = OperationMode.AUTOMATIC
    ipad: IpadConfig = field(default_factory=IpadConfig)
    autostart_on_login: bool = True
    debounce_seconds: float = 4.0
    max_retries: int = 3
    retry_interval: float = 3.0
    cooldown_seconds: float = 30.0
    ignore_list: List[str] = field(default_factory=lambda: ["Dummy", "Virtual", "Capture"])
    virtual_display_name: str = DEFAULT_VIRTUAL_DISPLAY_NAME
    betterdisplaycli_path: Optional[str] = None
    swiftbar_plugin_id: str = SWIFTBAR_PLUGIN_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "ipad": self.ipad.to_dict(),
            "autostart_on_login": self.autostart_on_login,
            "debounce_seconds": self.debounce_seconds,
            "max_retries": self.max_retries,
            "retry_interval": self.retry_interval,
            "cooldown_seconds": self.cooldown_seconds,
            "ignore_list": self.ignore_list,
            "virtual_display_name": self.virtual_display_name,
            "betterdisplaycli_path": self.betterdisplaycli_path,
            "swiftbar_plugin_id": self.swiftbar_plugin_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        mode_str = data.get("mode", OperationMode.AUTOMATIC.value)
        try:
            mode = OperationMode(mode_str)
        except ValueError:
            mode = OperationMode.AUTOMATIC

        ipad_data = data.get("ipad", {})
        ipad = IpadConfig(
            name=ipad_data.get("name", ""),
            sidecar_uuid=ipad_data.get("sidecar_uuid", ""),
            usb_serial=ipad_data.get("usb_serial", ""),
        )

        return cls(
            mode=mode,
            ipad=ipad,
            autostart_on_login=bool(data.get("autostart_on_login", True)),
            debounce_seconds=float(data.get("debounce_seconds", 4.0)),
            max_retries=int(data.get("max_retries", 3)),
            retry_interval=float(data.get("retry_interval", 3.0)),
            cooldown_seconds=float(data.get("cooldown_seconds", 30.0)),
            ignore_list=list(data.get("ignore_list", ["Dummy", "Virtual", "Capture"])),
            virtual_display_name=str(data.get("virtual_display_name", DEFAULT_VIRTUAL_DISPLAY_NAME)),
            betterdisplaycli_path=data.get("betterdisplaycli_path"),
            swiftbar_plugin_id=str(data.get("swiftbar_plugin_id", SWIFTBAR_PLUGIN_ID)),
        )


def load_config() -> Config:
    """Load config from ~/Library/Application Support/PadPilot/config.json with /tmp fallback."""
    target_file = None
    if CONFIG_FILE.exists():
        target_file = CONFIG_FILE
    elif Path("/tmp/PadPilot/config.json").exists():
        target_file = Path("/tmp/PadPilot/config.json")

    if not target_file:
        cfg = Config()
        save_config(cfg)
        return cfg

    try:
        with open(target_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Config.from_dict(data)
    except Exception as e:
        logger.error(f"Failed to read {target_file}, loading default: {e}")
        return Config()


def save_config(cfg: Config) -> None:
    """Atomically save config to ~/Library/Application Support/PadPilot/config.json with /tmp fallback."""
    for target_dir, target_file in [
        (APP_SUPPORT_DIR, CONFIG_FILE),
        (Path("/tmp/PadPilot"), Path("/tmp/PadPilot/config.json")),
    ]:
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            tmp_file = target_dir / f"config.json.{os.getpid()}_{time.time()}.tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(cfg.to_dict(), f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, target_file)
            logger.info(f"Saved configuration successfully to {target_file}")
            return
        except (PermissionError, OSError) as e:
            if target_dir == APP_SUPPORT_DIR:
                continue
            logger.error(f"Failed to save configuration: {e}")


def write_atomic_status(snapshot: StatusSnapshot) -> None:
    """Atomically write runtime status snapshot.
    
    Prevents race condition where SwiftBar reads a partially written file.
    Uses unique temp file name to prevent collision between concurrent writes.
    """
    for r_dir, s_file in [
        (RUNTIME_DIR, STATUS_FILE),
        (Path("/tmp/PadPilot/runtime"), Path("/tmp/PadPilot/runtime/status.json")),
    ]:
        tmp_file = None
        try:
            r_dir.mkdir(parents=True, exist_ok=True)
            tmp_file = r_dir / f"status.json.{os.getpid()}_{threading.get_ident()}_{time.time()}.tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(snapshot.to_dict(), f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, s_file)
            return
        except (PermissionError, OSError) as e:
            if tmp_file and tmp_file.exists():
                try:
                    tmp_file.unlink()
                except OSError:
                    pass
            if r_dir == RUNTIME_DIR:
                continue
            logger.warning(f"Failed to write atomic status: {e}")


def read_status() -> Optional[dict[str, Any]]:
    """Read the latest status snapshot. Returns None if missing or corrupted."""
    target_file = None
    if STATUS_FILE.exists():
        target_file = STATUS_FILE
    elif Path("/tmp/PadPilot/runtime/status.json").exists():
        target_file = Path("/tmp/PadPilot/runtime/status.json")

    if not target_file:
        return None
    try:
        with open(target_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not read {target_file}: {e}")
        return None


def get_status_file_path() -> Path:
    return STATUS_FILE


def get_config_file_path() -> Path:
    return CONFIG_FILE
