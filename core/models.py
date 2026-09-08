"""Data models and enums for PadPilot."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, List, Optional, Tuple

SWIFTBAR_PLUGIN_ID = "padpilot.30s.py"
DEFAULT_VIRTUAL_DISPLAY_NAME = "PadPilotVirtual"


class OperationMode(str, Enum):
    AUTOMATIC = "automatic"
    MANUAL_ONLY = "manual_only"
    PREFER_IPAD = "prefer_ipad"


class DisplayRole(str, Enum):
    PHYSICAL = "PHYSICAL"
    IPAD_MAIN = "IPAD_MAIN"
    IPAD_SECONDARY = "IPAD_SECONDARY"
    VIRTUAL = "VIRTUAL"
    NO_CHANGE = "NO_CHANGE"


class TransitionState(str, Enum):
    IDLE = "IDLE"
    CONNECTING_SIDECAR = "CONNECTING_SIDECAR"
    WAITING_FOR_DISPLAY = "WAITING_FOR_DISPLAY"
    SETTING_MAIN = "SETTING_MAIN"
    COOLDOWN = "COOLDOWN"


class IconStatus(str, Enum):
    PHYSICAL = "🖥️"
    IPAD = "📱"
    VIRTUAL = "◻️"
    WARNING = "⚠️"
    PAUSED = "⏸️"


@dataclass
class DisplayInfo:
    display_id: int
    name: str
    uuid: Optional[str] = None
    is_main: bool = False
    is_builtin: bool = False
    is_virtual: bool = False
    is_sidecar: bool = False
    width: int = 0
    height: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IpadConfig:
    name: str = ""
    sidecar_uuid: str = ""
    usb_serial: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UserOverride:
    target_role: DisplayRole
    topology_generation: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_role": self.target_role.value,
            "topology_generation": self.topology_generation,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> Optional[UserOverride]:
        if not data:
            return None
        return cls(
            target_role=DisplayRole(data["target_role"]),
            topology_generation=int(data["topology_generation"]),
            timestamp=float(data.get("timestamp", time.time())),
        )


@dataclass
class ActualState:
    physical_displays: List[DisplayInfo] = field(default_factory=list)
    main_display: Optional[DisplayInfo] = None
    virtual_display_exists: bool = False
    virtual_display_connected: bool = False
    ipad_usb_present: bool = False
    sidecar_available: bool = False
    sidecar_connected: bool = False
    sidecar_display_online: bool = False
    sleeping: bool = False
    topology_generation: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "physical_displays": [d.to_dict() for d in self.physical_displays],
            "main_display": self.main_display.to_dict() if self.main_display else None,
            "virtual_display_exists": self.virtual_display_exists,
            "virtual_display_connected": self.virtual_display_connected,
            "ipad_usb_present": self.ipad_usb_present,
            "sidecar_available": self.sidecar_available,
            "sidecar_connected": self.sidecar_connected,
            "sidecar_display_online": self.sidecar_display_online,
            "sleeping": self.sleeping,
            "topology_generation": self.topology_generation,
            "timestamp": self.timestamp,
        }


@dataclass
class DesiredState:
    target_display_role: DisplayRole
    reason: str
    needs_sidecar_connect: bool = False
    needs_sidecar_disconnect: bool = False
    needs_main_display_target: Optional[str] = None  # "ipad", "physical", "virtual"

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_display_role": self.target_display_role.value,
            "reason": self.reason,
            "needs_sidecar_connect": self.needs_sidecar_connect,
            "needs_sidecar_disconnect": self.needs_sidecar_disconnect,
            "needs_main_display_target": self.needs_main_display_target,
        }


@dataclass
class RuntimeState:
    mode: OperationMode = OperationMode.AUTOMATIC
    user_override: Optional[UserOverride] = None
    transition_state: TransitionState = TransitionState.IDLE
    retry_count: int = 0
    cooldown_until: float = 0.0
    debounce_until: float = 0.0
    debounce_target_role: Optional[DisplayRole] = None
    last_topology_signature: Tuple[Any, ...] = ()
    topology_generation: int = 0
    dirty: bool = False
    last_error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "user_override": self.user_override.to_dict() if self.user_override else None,
            "transition_state": self.transition_state.value,
            "retry_count": self.retry_count,
            "cooldown_until": self.cooldown_until,
            "debounce_until": self.debounce_until,
            "debounce_target_role": self.debounce_target_role.value if self.debounce_target_role else None,
            "topology_generation": self.topology_generation,
            "dirty": self.dirty,
            "last_error": self.last_error,
        }


@dataclass
class StatusSnapshot:
    """Atomic status snapshot exported for SwiftBar UI and CLI consumption."""
    timestamp: float
    mode: str
    icon: str
    actual: dict[str, Any]
    desired: dict[str, Any]
    runtime: dict[str, Any]
    configured_ipad: dict[str, Any]
    summary_text: str
    status_details: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
