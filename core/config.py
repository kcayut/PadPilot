"""Configuration and runtime state persistence for PadPilot."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
from uuid import UUID
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from core.logger import get_logger
from core.storage import atomic_write, latest_state_path, private_directory, read_private_json
from core.models import (
    DEFAULT_VIRTUAL_DISPLAY_NAME,
    IpadConfig,
    OperationMode,
    StatusSnapshot,
    pairing_key,
)

logger = get_logger("Config")

HOTKEY_NAMED_KEYS = {
    'space', 'tab', 'return', 'delete', 'forwarddelete', 'escape',
    'home', 'end', 'pageup', 'pagedown', 'left', 'right', 'up', 'down',
    'equal', 'minus', 'leftbracket', 'rightbracket', 'quote', 'semicolon',
    'backslash', 'comma', 'slash', 'period', 'grave',
    *(f'f{i}' for i in range(1, 21)),
}

def validate_connection_hotkey(value: str) -> str:
    """A supported physical key with explicit modifiers; empty disables registration."""
    if not isinstance(value, str):
        raise ValueError('Invalid connection hotkey')
    if not value:
        return value
    parts = value.split('+')
    modifiers = parts[:-1]
    order = ('ctrl', 'alt', 'shift', 'cmd')
    if ((not re.fullmatch('[a-z0-9]', parts[-1]) and parts[-1] not in HOTKEY_NAMED_KEYS) or not modifiers
            or len(set(modifiers)) != len(modifiers)
            or any(item not in order for item in modifiers)
            or not {'ctrl', 'cmd'}.intersection(modifiers)):
        raise ValueError('Invalid connection hotkey')
    return '+'.join([item for item in order if item in modifiers] + [parts[-1]])

APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "PadPilot"
CONFIG_FILE = APP_SUPPORT_DIR / "config.json"
RUNTIME_DIR = APP_SUPPORT_DIR / "runtime"
STATUS_FILE = RUNTIME_DIR / "status.json"
FALLBACK_DIR = Path("/tmp/PadPilot")
FALLBACK_CONFIG_FILE = FALLBACK_DIR / "config.json"

try:
    private_directory(APP_SUPPORT_DIR)
except (PermissionError, OSError):
    APP_SUPPORT_DIR = Path("/tmp/PadPilot")
    CONFIG_FILE = APP_SUPPORT_DIR / "config.json"
    RUNTIME_DIR = APP_SUPPORT_DIR / "runtime"
    STATUS_FILE = RUNTIME_DIR / "status.json"
    private_directory(APP_SUPPORT_DIR)


@dataclass
class Config:
    language: str = 'zh-Hant'
    mode: OperationMode = OperationMode.MANUAL_ONLY
    ipad: IpadConfig = field(default_factory=IpadConfig)
    paired_ipads: List[IpadConfig] = field(default_factory=list)
    autostart_on_login: bool = True
    usb_event_wakeup: bool = True
    auto_detect_ipad: bool = True
    connection_hotkey: str = ''
    connect_on_boot: bool = True
    debounce_seconds: float = 4.0
    max_retries: int = 3
    retry_interval: float = 3.0
    cooldown_seconds: float = 30.0
    ignore_list: List[str] = field(default_factory=lambda: ["Dummy", "Virtual", "Capture"])
    virtual_display_name: str = DEFAULT_VIRTUAL_DISPLAY_NAME
    betterdisplaycli_path: Optional[str] = None
    revision: int = 1
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "mode": self.mode.value,
            "ipad": self.ipad.to_dict(),
            "paired_ipads": [ipad.to_dict() for ipad in self.paired_ipads],
            "autostart_on_login": self.autostart_on_login,
            "usb_event_wakeup": self.usb_event_wakeup,
            "auto_detect_ipad": self.auto_detect_ipad,
            "connection_hotkey": self.connection_hotkey,
            "connect_on_boot": self.connect_on_boot,
            "debounce_seconds": self.debounce_seconds,
            "max_retries": self.max_retries,
            "retry_interval": self.retry_interval,
            "cooldown_seconds": self.cooldown_seconds,
            "ignore_list": self.ignore_list,
            "virtual_display_name": self.virtual_display_name,
            "betterdisplaycli_path": self.betterdisplaycli_path,
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
        if not isinstance(data, dict):
            raise ValueError('Configuration must be a JSON object')
        profiles = data.get('paired_ipads', [])
        if not isinstance(profiles, list):
            raise ValueError('paired_ipads must be a list')
        for profile in [data.get('ipad', {}), *profiles]:
            if not isinstance(profile, dict) or any(
                not isinstance(profile.get(key, ''), str) or len(profile.get(key, '')) > 256
                or any(ord(c) < 32 for c in profile.get(key, ''))
                for key in ('name', 'sidecar_uuid', 'usb_serial')
            ):
                raise ValueError('Invalid iPad configuration')
        for key in ('autostart_on_login', 'usb_event_wakeup', 'auto_detect_ipad', 'connect_on_boot'):
            if key in data and type(data[key]) is not bool:
                raise ValueError(f'{key} must be a boolean')
        for key in ('debounce_seconds', 'retry_interval', 'cooldown_seconds', 'updated_at', 'max_retries', 'revision'):
            if key not in data:
                continue
            value = data[key]
            if (type(value) not in (int, float) or not math.isfinite(value) or value < 0
                    or (key in ('max_retries', 'revision') and (type(value) is not int or value < 1))):
                raise ValueError(f'Invalid {key}')
        if not isinstance(data.get('ignore_list', []), list) or any(
            not isinstance(item, str) for item in data.get('ignore_list', [])
        ):
            raise ValueError('ignore_list must contain strings')
        if not isinstance(data.get('virtual_display_name', DEFAULT_VIRTUAL_DISPLAY_NAME), str):
            raise ValueError('Invalid virtual_display_name')
        if data.get('betterdisplaycli_path') is not None and not isinstance(data['betterdisplaycli_path'], str):
            raise ValueError('Invalid betterdisplaycli_path')
        mode_str = data.get("mode", OperationMode.MANUAL_ONLY.value)
        mode = OperationMode(mode_str)

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
            language=data.get('language') if data.get('language') in ('zh-Hant', 'en', 'ja') else 'zh-Hant',
            mode=mode,
            ipad=ipad,
            paired_ipads=paired,
            autostart_on_login=bool(data.get("autostart_on_login", True)),
            usb_event_wakeup=data.get("usb_event_wakeup", True) is True,
            auto_detect_ipad=data.get("auto_detect_ipad", True) is True,
            connection_hotkey=validate_connection_hotkey(data.get('connection_hotkey', '')),
            connect_on_boot=data.get('connect_on_boot', True),
            debounce_seconds=float(data.get("debounce_seconds", 4.0)),
            max_retries=int(data.get("max_retries", 3)),
            retry_interval=float(data.get("retry_interval", 3.0)),
            cooldown_seconds=float(data.get("cooldown_seconds", 30.0)),
            ignore_list=list(data.get("ignore_list", ["Dummy", "Virtual", "Capture"])),
            virtual_display_name=str(data.get("virtual_display_name", DEFAULT_VIRTUAL_DISPLAY_NAME)),
            betterdisplaycli_path=data.get("betterdisplaycli_path"),
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


def detect_system_language() -> str:
    """Detect preferred macOS language; defaults to 'en' unless Traditional Chinese or Japanese.

    Rules:
    - zh-Hant, zh-TW, zh-HK, zh-MO -> 'zh-Hant'
    - ja-* -> 'ja'
    - All other languages, including zh-Hans, zh-CN, zh-SG, en-*, or fallback -> 'en'
    """
    try:
        res = subprocess.run(
            ["defaults", "read", "-g", "AppleLanguages"],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
        if res.returncode == 0 and res.stdout:
            matches = re.findall(r'"([^"]+)"', res.stdout)
            if matches:
                primary = matches[0].lower()
                if primary.startswith(("zh-hant", "zh-tw", "zh-hk", "zh-mo")):
                    return "zh-Hant"
                if primary.startswith("ja"):
                    return "ja"
                return "en"
    except Exception:
        pass

    # Fallback to environment variables
    lang_env = (os.environ.get("LANG") or os.environ.get("LC_ALL") or "").lower()
    if lang_env.startswith(("zh_tw", "zh_hk", "zh_mo", "zh-hant")):
        return "zh-Hant"
    if lang_env.startswith("ja"):
        return "ja"

    return "en"


def load_config() -> Config:
    """Load config from ~/Library/Application Support/PadPilot/config.json with /tmp fallback."""
    target_file = get_config_file_path()
    if not target_file.exists():
        cfg = Config(language=detect_system_language())
        save_config(cfg)
        return cfg

    try:
        data = read_private_json(target_file)
        return Config.from_dict(data)
    except (OSError, ValueError, TypeError, KeyError) as e:
        raise ValueError(f'Cannot load configuration: {target_file}. '
                         'Repair or restore this file before starting PadPilot; no defaults were applied.') from e


def save_config(cfg: Config) -> None:
    """Atomically save config to ~/Library/Application Support/PadPilot/config.json."""
    content = json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False).encode("utf-8")
    try:
        atomic_write(CONFIG_FILE, content)
        target_file = CONFIG_FILE
    except OSError:
        target_file = FALLBACK_CONFIG_FILE
        atomic_write(target_file, content)
    logger.info(f"Saved configuration successfully to {target_file}")


def write_atomic_status(snapshot: StatusSnapshot) -> None:
    """Atomically replace status with private permissions, including fallback."""
    content = json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False).encode("utf-8")
    try:
        atomic_write(STATUS_FILE, content)
    except OSError:
        atomic_write(FALLBACK_DIR / "runtime/status.json", content)


def read_status() -> Optional[dict[str, Any]]:
    """Read the latest status snapshot. Returns None if missing or corrupted."""
    try:
        target_file = get_status_file_path()
        if not target_file.exists():
            return None
        value = read_private_json(target_file)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError) as e:
        logger.warning(f"Could not read status: {e}")
        return None


def get_status_file_path() -> Path:
    return latest_state_path(STATUS_FILE, FALLBACK_DIR / 'runtime/status.json')


def get_config_file_path() -> Path:
    return latest_state_path(CONFIG_FILE, FALLBACK_CONFIG_FILE)
