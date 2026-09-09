"""Configuration and runtime state persistence for PadPilot."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from uuid import UUID
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
    pairing_key,
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
    paired_ipads: List[IpadConfig] = field(default_factory=list)
    autostart_on_login: bool = True
    debounce_seconds: float = 4.0
    max_retries: int = 3
    retry_interval: float = 3.0
    cooldown_seconds: float = 30.0
    ignore_list: List[str] = field(default_factory=lambda: ["Dummy", "Virtual", "Capture"])
    virtual_display_name: str = DEFAULT_VIRTUAL_DISPLAY_NAME
    betterdisplaycli_path: Optional[str] = None
    swiftbar_plugin_id: str = SWIFTBAR_PLUGIN_ID
    revision: int = 1
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "ipad": self.ipad.to_dict(),
            "paired_ipads": [ipad.to_dict() for ipad in self.paired_ipads],
            "autostart_on_login": self.autostart_on_login,
            "debounce_seconds": self.debounce_seconds,
            "max_retries": self.max_retries,
            "retry_interval": self.retry_interval,
            "cooldown_seconds": self.cooldown_seconds,
            "ignore_list": self.ignore_list,
            "virtual_display_name": self.virtual_display_name,
            "betterdisplaycli_path": self.betterdisplaycli_path,
            "swiftbar_plugin_id": self.swiftbar_plugin_id,
            "revision": self.revision,
            "updated_at": self.updated_at,
        }

    def semantic_dict(self) -> dict[str, Any]:
        data = self.to_dict()
        data.pop("revision", None)
        data.pop("updated_at", None)
        return data

    def content_equals(self, other: object) -> bool:
        if not isinstance(other, Config):
            return False
        return self.semantic_dict() == other.semantic_dict()

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

        paired = [IpadConfig(**{key: item.get(key, "") for key in ("name", "sidecar_uuid", "usb_serial")})
                  for item in data.get("paired_ipads", [])]
        if any(ipad.to_dict().values()) and ipad not in paired:
            paired.append(ipad)
        return cls(
            mode=mode,
            ipad=ipad,
            paired_ipads=paired,
            autostart_on_login=bool(data.get("autostart_on_login", True)),
            debounce_seconds=float(data.get("debounce_seconds", 4.0)),
            max_retries=int(data.get("max_retries", 3)),
            retry_interval=float(data.get("retry_interval", 3.0)),
            cooldown_seconds=float(data.get("cooldown_seconds", 30.0)),
            ignore_list=list(data.get("ignore_list", ["Dummy", "Virtual", "Capture"])),
            virtual_display_name=str(data.get("virtual_display_name", DEFAULT_VIRTUAL_DISPLAY_NAME)),
            betterdisplaycli_path=data.get("betterdisplaycli_path"),
            swiftbar_plugin_id=str(data.get("swiftbar_plugin_id", SWIFTBAR_PLUGIN_ID)),
            revision=int(data.get("revision", 1)),
            updated_at=float(data.get("updated_at", 0.0)),
        )

    def remember_ipad(self, data: dict, activate: bool = False) -> bool:
        """Upsert by stable identity; return whether the active target changed."""
        if not isinstance(data, dict) or set(data) - {"name", "sidecar_uuid", "usb_serial"}:
            raise ValueError("無效的配對資料")
        values = {key: data.get(key, "") for key in ("name", "sidecar_uuid", "usb_serial")}
        if any(not isinstance(v, str) or len(v) > 256 or any(ord(c) < 32 for c in v)
               for v in values.values()):
            raise ValueError("配對資料含無效字元或過長")
        if values["sidecar_uuid"]:
            values["sidecar_uuid"] = str(UUID(values["sidecar_uuid"])).upper()
        if not values["name"] or not (values["sidecar_uuid"] or values["usb_serial"]):
            raise ValueError("請提供名稱與 Sidecar UUID 或 USB 序號")
        device = IpadConfig(**values)
        matches = [p for p in self.paired_ipads if (
            device.sidecar_uuid and p.sidecar_uuid.upper() == device.sidecar_uuid
        ) or (device.usb_serial and p.usb_serial == device.usb_serial)]
        if len(matches) > 1:
            raise ValueError("Sidecar UUID 與 USB 序號對應到不同紀錄，請先確認裝置")
        previous = matches[0] if matches else None
        if previous and self.ipad == previous and device != previous and not activate:
            raise ValueError("更新目前目標需同時選擇套用為控制目標")
        if previous:
            self.paired_ipads[self.paired_ipads.index(previous)] = device
        else:
            self.paired_ipads.append(device)
        changed = activate and self.ipad != device
        if activate:
            self.ipad = device
        return changed

    def forget_ipad(self, key: str) -> bool:
        matches = [p for p in self.paired_ipads if pairing_key(p.to_dict()) == key]
        if len(matches) != 1:
            raise ValueError("配對紀錄已變更或不存在，請重新開啟清單。")
        device = matches[0]
        active = self.ipad == device
        self.paired_ipads.remove(device)
        if active:
            self.ipad = IpadConfig()
            # Deleting the target must not reconnect an arbitrary iPad or drop a display.
            self.mode = OperationMode.MANUAL_ONLY
        return active


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
    """Atomically save config to ~/Library/Application Support/PadPilot/config.json."""
    target_dir = APP_SUPPORT_DIR
    target_file = CONFIG_FILE
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError):
        target_dir = Path("/tmp/PadPilot")
        target_file = target_dir / "config.json"
        target_dir.mkdir(parents=True, exist_ok=True)

    tmp_file = target_dir / f"config.json.{os.getpid()}_{time.time()}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_file, target_file)
    logger.info(f"Saved configuration successfully to {target_file}")


def write_atomic_status(snapshot: StatusSnapshot) -> None:
    """Atomically write runtime status snapshot.
    
    Prevents race condition where SwiftBar reads a partially written file.
    Uses unique temp file name to prevent collision between concurrent writes.
    """
    r_dir = RUNTIME_DIR
    s_file = STATUS_FILE
    try:
        r_dir.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError):
        r_dir = Path("/tmp/PadPilot/runtime")
        s_file = r_dir / "status.json"
        r_dir.mkdir(parents=True, exist_ok=True)

    tmp_file = r_dir / f"status.json.{os.getpid()}_{threading.get_ident()}_{time.time()}.tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(snapshot.to_dict(), f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, s_file)
    except Exception as e:
        if tmp_file and tmp_file.exists():
            try:
                tmp_file.unlink()
            except OSError:
                pass
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
