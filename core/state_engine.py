"""Display State Engine for PadPilot.

Implements the core decision cycle:
    observe() -> ActualState
    policy(actual, config, override) -> DesiredState
    is_satisfied(actual, desired) -> bool
    transition() -> execute transitions under single-flight lock
"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Any, Optional, Tuple

from core.betterdisplay import BetterDisplayCLI
from core.config import Config, write_atomic_status
from core.detector import DisplayDetector
from core.logger import get_logger
from core.models import (
    ActualState,
    DesiredState,
    DisplayRole,
    IconStatus,
    OperationMode,
    RuntimeState,
    StatusSnapshot,
    TransitionState,
    UserOverride,
)
from core.notifier import notify_error

logger = get_logger("StateEngine")


class StateEngine:
    """Manages display automation, state transitions, debounce, and user overrides."""

    def __init__(self, config: Config, detector: DisplayDetector, bd_cli: BetterDisplayCLI) -> None:
        self.config = config
        self.detector = detector
        self.bd_cli = bd_cli

        self.runtime = RuntimeState(mode=config.mode)
        self.actual: Optional[ActualState] = None
        self.desired: Optional[DesiredState] = None

        self._transition_lock = threading.Lock()
        # ponytail: serialize one display topology; use a command queue if IPC latency matters.
        self._eval_lock = threading.RLock()

    def set_mode(self, mode: OperationMode) -> None:
        """Update operational mode."""
        with self._eval_lock:
            logger.info(f"Mode changed: {self.runtime.mode} -> {mode}")
            self.runtime.mode = mode
            self.config.mode = mode
            # Reset runtime transient overrides if mode explicitly changed
            self.runtime.user_override = None
            self.evaluate(trigger="mode_change")

    def set_user_override(self, target_role: DisplayRole, async_transition: bool = True) -> None:
        """Set a user manual override bound to current topology generation."""
        with self._eval_lock:
            self._observe()
            override = UserOverride(
                target_role=target_role,
                topology_generation=self.runtime.topology_generation,
                timestamp=time.time(),
            )
            logger.info(
                f"User override registered: {target_role.value} at generation {self.runtime.topology_generation}"
            )
            self.runtime.user_override = override
            self.evaluate(trigger=f"override_{target_role.value.lower()}", async_transition=async_transition)

    def clear_user_override(self, async_transition: bool = True) -> None:
        """Clear active user manual override."""
        with self._eval_lock:
            logger.info("Clearing active user override")
            self.runtime.user_override = None
            self.evaluate(trigger="clear_override", async_transition=async_transition)

    def reset_automation(self, async_transition: bool = True) -> None:
        """Reset runtime transient state without wiping persistent preferences."""
        with self._eval_lock:
            logger.info("Resetting display automation runtime state")
            self.runtime.retry_count = 0
            self.runtime.cooldown_until = 0.0
            self.runtime.debounce_until = 0.0
            self.runtime.debounce_target_role = None
            self.runtime.user_override = None
            self.runtime.last_error = None
            self.runtime.transition_state = TransitionState.IDLE
            self.evaluate(trigger="manual_reset", async_transition=async_transition)

    def reconnect_sidecar(self) -> bool:
        with self._eval_lock:
            actual = self._observe()
            specifier = self.config.ipad.sidecar_uuid or self.config.ipad.name
            role = self.runtime.user_override.target_role if self.runtime.user_override else None
            if role not in (DisplayRole.IPAD_MAIN, DisplayRole.IPAD_SECONDARY):
                role = DisplayRole.IPAD_MAIN
                if actual.physical_displays and self.runtime.mode != OperationMode.PREFER_IPAD:
                    role = DisplayRole.IPAD_SECONDARY
            if actual.sidecar_connected and not self.bd_cli.disconnect_sidecar(specifier):
                return False
            self.runtime.cooldown_until = 0.0
            self.runtime.retry_count = 0
            self.set_user_override(role)
            return True

    def check_debounce(self, had_physical: bool, now_has_physical: bool) -> bool:
        """Evaluate debounce timer when physical display disappears.
        
        Returns:
            True if debounce is active (should wait), False otherwise.
        """
        now = time.time()
        # Physical display just disappeared
        if had_physical and not now_has_physical:
            if self.runtime.debounce_until <= now:
                self.runtime.debounce_until = now + self.config.debounce_seconds
                logger.info(
                    f"Physical display disconnected. Starting debounce for {self.config.debounce_seconds}s..."
                )
                return True

        # If currently waiting in debounce window
        if self.runtime.debounce_until > now:
            if now_has_physical:
                logger.info("Physical display returned during debounce window. Debounce cancelled.")
                self.runtime.debounce_until = 0.0
                return False
            return True

        # Debounce expired
        if self.runtime.debounce_until > 0 and self.runtime.debounce_until <= now:
            self.runtime.debounce_until = 0.0

        return False

    def is_satisfied(self, actual: ActualState, desired: DesiredState) -> bool:
        """Semantic fulfillment check between ActualState and DesiredState.
        
        Per engineering requirements, avoid raw dataclass equality.
        """
        if desired.needs_sidecar_disconnect and actual.sidecar_connected:
            return False
        target = desired.target_display_role

        if target == DisplayRole.NO_CHANGE:
            return True

        if target == DisplayRole.PHYSICAL:
            # Satisfied if at least one physical display is present and main
            if not actual.physical_displays:
                return False
            return bool(actual.main_display and any(
                d.display_id == actual.main_display.display_id for d in actual.physical_displays
            ))

        if target == DisplayRole.IPAD_MAIN:
            # Satisfied if Sidecar is connected, display is online, and main is Sidecar/iPad
            if not (actual.sidecar_connected and actual.sidecar_display_online):
                return False
            if actual.main_display and (actual.main_display.is_sidecar or (
                self.config.ipad.name and self.config.ipad.name.lower() in actual.main_display.name.lower()
            )):
                return True
            return False

        if target == DisplayRole.IPAD_SECONDARY:
            # Satisfied if Sidecar is connected and online, but NOT main
            if not (actual.sidecar_connected and actual.sidecar_display_online):
                return False
            if not actual.main_display or actual.main_display.is_sidecar:
                return False
            if actual.physical_displays:
                return any(d.display_id == actual.main_display.display_id for d in actual.physical_displays)
            return (actual.main_display.is_virtual and
                    actual.main_display.name.casefold() == self.config.virtual_display_name.casefold())

        if target == DisplayRole.VIRTUAL:
            # Satisfied if fallback virtual display is connected and main
            if (actual.virtual_display_connected and actual.main_display and actual.main_display.is_virtual
                    and actual.main_display.name.casefold() == self.config.virtual_display_name.casefold()):
                return True
            return False

        return False

    def policy(self, actual: ActualState, config: Config, runtime: RuntimeState) -> DesiredState:
        desired = self._policy(actual, config, runtime)
        # Every path requesting a connection obeys the same cooldown.
        if desired.needs_sidecar_connect and runtime.cooldown_until > time.time():
            target = DisplayRole.PHYSICAL if actual.physical_displays else DisplayRole.VIRTUAL
            return DesiredState(
                target_display_role=target,
                reason="Sidecar connection in cooldown. Keeping fallback display available.",
                needs_main_display_target="physical" if actual.physical_displays else "virtual",
            )
        if desired.target_display_role in (DisplayRole.PHYSICAL, DisplayRole.VIRTUAL):
            desired.needs_main_display_target = "physical" if desired.target_display_role == DisplayRole.PHYSICAL else "virtual"
        return desired

    def _policy(self, actual: ActualState, config: Config, runtime: RuntimeState) -> DesiredState:
        """Evaluate policy rules and calculate DesiredState with clear Reason."""
        now = time.time()

        # 1. Check User Override
        if runtime.user_override:
            if runtime.user_override.topology_generation == runtime.topology_generation:
                override_role = runtime.user_override.target_role
                if override_role == DisplayRole.IPAD_DISCONNECTED:
                    return DesiredState(
                        target_display_role=DisplayRole.PHYSICAL if actual.physical_displays else DisplayRole.VIRTUAL,
                        reason="User requested iPad disconnect. Automatic reconnection paused until reset, mode or topology change.",
                        needs_sidecar_disconnect=actual.sidecar_connected,
                        needs_main_display_target="physical" if actual.physical_displays else "virtual",
                    )
                if override_role == DisplayRole.IPAD_SECONDARY:
                    needs_main = "physical" if actual.physical_displays else "virtual"
                    return DesiredState(
                        target_display_role=DisplayRole.IPAD_SECONDARY,
                        reason=f"User Override active: Use iPad as Secondary (Topology Gen {runtime.topology_generation}).",
                        needs_sidecar_connect=not actual.sidecar_connected,
                        needs_main_display_target=needs_main,
                    )
                elif override_role == DisplayRole.IPAD_MAIN:
                    return DesiredState(
                        target_display_role=DisplayRole.IPAD_MAIN,
                        reason=f"User Override active: Use iPad as Main (Topology Gen {runtime.topology_generation}).",
                        needs_sidecar_connect=not actual.sidecar_connected,
                        needs_main_display_target="ipad",
                    )
            else:
                logger.info(
                    f"Topology generation changed ({runtime.user_override.topology_generation} -> {runtime.topology_generation}). "
                    "Expiring user override."
                )
                runtime.user_override = None

        # 2. Check Mode: MANUAL_ONLY
        if runtime.mode == OperationMode.MANUAL_ONLY:
            return DesiredState(
                target_display_role=DisplayRole.NO_CHANGE,
                reason="Manual Only mode: automation is paused. Use Menu Bar for manual control.",
            )

        # 3. Check Mode: PREFER_IPAD
        if runtime.mode == OperationMode.PREFER_IPAD:
            if actual.sidecar_available or actual.ipad_usb_present or actual.sidecar_connected:
                return DesiredState(
                    target_display_role=DisplayRole.IPAD_MAIN,
                    reason="Prefer iPad mode: attempting to set iPad as Main display.",
                    needs_sidecar_connect=not actual.sidecar_connected,
                    needs_main_display_target="ipad",
                )
            else:
                return DesiredState(
                    target_display_role=DisplayRole.PHYSICAL if actual.physical_displays else DisplayRole.VIRTUAL,
                    reason="Prefer iPad mode: configured iPad not detected, using fallback display.",
                )

        # 4. Mode: AUTOMATIC (Default)
        # Case A: Physical display present
        if len(actual.physical_displays) > 0:
            first_disp = actual.physical_displays[0].name
            needs_main = "physical"
            # If Sidecar is already connected (e.g. wireless or user enabled), respect it and do NOT disconnect
            if actual.sidecar_connected and actual.sidecar_display_online:
                return DesiredState(
                    target_display_role=DisplayRole.IPAD_SECONDARY,
                    reason=f"Physical display detected ({first_disp}) with active Sidecar. Keeping iPad as Secondary.",
                    needs_main_display_target=needs_main,
                )
            return DesiredState(
                target_display_role=DisplayRole.PHYSICAL,
                reason=f"Physical display detected ({first_disp}). Automatic Sidecar not required.",
                needs_main_display_target=needs_main,
            )

        # Case B: No physical display, but debounce is pending
        if runtime.debounce_until > now:
            remaining = runtime.debounce_until - now
            return DesiredState(
                target_display_role=DisplayRole.NO_CHANGE,
                reason=f"Physical display disconnected. Waiting debounce ({remaining:.1f}s remaining)...",
            )

        # Case C: No physical display + Configured USB iPad connected OR Sidecar target available
        if actual.ipad_usb_present or actual.sidecar_available or actual.sidecar_connected:
            via_msg = "USB" if actual.ipad_usb_present else "Sidecar Continuity/Wireless"
            return DesiredState(
                target_display_role=DisplayRole.IPAD_MAIN,
                reason=f"Mac mini is headless and configured iPad is detected ({via_msg}). Activating Sidecar Main.",
                needs_sidecar_connect=not actual.sidecar_connected,
                needs_main_display_target="ipad",
            )

        # Case D: No physical display + No USB iPad / Sidecar target
        return DesiredState(
            target_display_role=DisplayRole.VIRTUAL,
            reason="No physical display or configured iPad detected. Using BetterDisplay Virtual Display fallback.",
            needs_main_display_target="virtual",
        )

    def _observe(self) -> ActualState:
        """Refresh topology and override validity on every observation path."""
        # 1. Observe
        had_physical = bool(self.actual and len(self.actual.physical_displays) > 0)
        had_sidecar = bool(self.actual and self.actual.sidecar_connected)
        actual, signature = self.detector.observe(current_generation=self.runtime.topology_generation)

        # If Sidecar was active and now disconnected while physical displays are present,
        # expire any user override targeting iPad so it does not auto-reconnect continuously.
        if (
            had_sidecar
            and not actual.sidecar_connected
            and len(actual.physical_displays) > 0
            and self.runtime.user_override
            and self.runtime.user_override.target_role in (DisplayRole.IPAD_SECONDARY, DisplayRole.IPAD_MAIN)
        ):
            logger.info(
                "Sidecar disconnected while physical display is present. Expiring iPad user override."
            )
            self.runtime.user_override = None

        # 2. Check Topology Signature changes (deterministic tuple comparison)
        if signature != self.runtime.last_topology_signature:
            if self.runtime.last_topology_signature:  # Don't increment on first initial observation
                self.runtime.topology_generation += 1
                logger.info(
                    f"Topology changed: generation {self.runtime.topology_generation}. Signature: {signature}"
                )
            self.runtime.last_topology_signature = signature
            actual.topology_generation = self.runtime.topology_generation

        now_has_physical = len(actual.physical_displays) > 0
        self.check_debounce(had_physical, now_has_physical)

        self.actual = actual
        return actual

    def evaluate(self, trigger: str = "periodic", async_transition: bool = True) -> None:
        """Run single evaluation cycle. Protected against re-entrant calls."""
        with self._eval_lock:
            actual = self._observe()

            # 3. Calculate Policy & DesiredState
            desired = self.policy(actual, self.config, self.runtime)

            self.actual = actual
            self.desired = desired

            # 4. Check Satisfaction
            satisfied = self.is_satisfied(actual, desired)

            phys_names = [d.name for d in actual.physical_displays]
            logger.info(
                f"Eval [{trigger}]: Mode={self.runtime.mode.value}, Physical={phys_names}, "
                f"USB_iPad={actual.ipad_usb_present}, SidecarAvail={actual.sidecar_available}, "
                f"SidecarConn={actual.sidecar_connected} => Desired={desired.target_display_role.value} "
                f"({desired.reason}) [Satisfied={satisfied}]"
            )

            # Export status immediately for UI
            self._export_status(satisfied=satisfied)

            if satisfied:
                # DO NOTHING
                return

            # If not satisfied, trigger transition under lock
            if async_transition:
                self._trigger_transition()
            else:
                self._run_transition()

    def _trigger_transition(self) -> None:
        """Execute state transition with single-flight lock."""
        if self._transition_lock.locked():
            logger.info("Transition already in progress. Marking runtime as dirty.")
            self.runtime.dirty = True
            return

        thread = threading.Thread(target=self._run_transition, daemon=True)
        thread.start()

    def _run_transition(self) -> None:
        """Single-flight transition execution thread."""
        with self._eval_lock, self._transition_lock:
            while True:
                self.runtime.dirty = False
                actual = self.actual
                desired = self.desired

                if not actual or not desired:
                    break

                if self.is_satisfied(actual, desired):
                    logger.info("Desired state satisfied. Ending transition.")
                    break

                target_role = desired.target_display_role
                logger.info(f"Starting transition to role: {target_role.value}")

                # Transition actions:
                success = True
                if desired.needs_sidecar_connect:
                    if (not actual.physical_displays and actual.virtual_display_exists
                            and not actual.virtual_display_connected):
                        if not self.bd_cli.connect_virtual_display(self.config.virtual_display_name):
                            logger.warning("Could not connect virtual fallback before Sidecar")
                    connected = False
                    while not connected and self.runtime.retry_count < self.config.max_retries:
                        self.runtime.transition_state = TransitionState.CONNECTING_SIDECAR
                        self._export_status(satisfied=False)

                        # Connect Sidecar
                        specifier = self.config.ipad.sidecar_uuid or self.config.ipad.name or "iPad"
                        connected = self.bd_cli.connect_sidecar(specifier)

                        if connected:
                            self.runtime.retry_count = 0
                            self.runtime.cooldown_until = 0.0
                            self.runtime.last_error = None
                            self.runtime.transition_state = TransitionState.WAITING_FOR_DISPLAY
                            self._export_status(satisfied=False)
                            # Wait for Sidecar display to register in macOS
                            time.sleep(1.0)
                            break
                        else:
                            self.runtime.retry_count += 1
                            logger.warning(
                                f"Sidecar connection attempt {self.runtime.retry_count}/{self.config.max_retries} failed."
                            )

                            if self.runtime.retry_count >= self.config.max_retries:
                                self.runtime.cooldown_until = time.time() + self.config.cooldown_seconds
                                self.runtime.transition_state = TransitionState.COOLDOWN
                                err_msg = f"Sidecar connection failed after {self.config.max_retries} attempts. Cooling down for {self.config.cooldown_seconds:.0f}s."
                                self.runtime.last_error = err_msg
                                logger.error(err_msg)
                                notify_error(err_msg, subtitle="Sidecar Connection Error")
                                self.runtime.retry_count = 0
                                success = False
                                break
                            time.sleep(self.config.retry_interval)

                if desired.needs_sidecar_connect and success:
                    # Hardware may have changed while the connection command was waiting.
                    actual = self._observe()
                    desired = self.policy(actual, self.config, self.runtime)
                    self.desired = desired

                if desired.needs_sidecar_disconnect:
                    specifier = self.config.ipad.sidecar_uuid or self.config.ipad.name
                    success = self.bd_cli.disconnect_sidecar(specifier)
                    if not success:
                        self.runtime.last_error = "Could not disconnect the configured iPad."

                if success and desired.needs_main_display_target:
                    self.runtime.transition_state = TransitionState.SETTING_MAIN
                    self._export_status(satisfied=False)

                    target_name = desired.needs_main_display_target
                    if target_name == "ipad":
                        spec = self.config.ipad.name or "iPad"
                        success = self.bd_cli.set_main_display(spec)
                    elif target_name == "virtual":
                        success = actual.virtual_display_connected or self.bd_cli.connect_virtual_display(self.config.virtual_display_name)
                        if success:
                            time.sleep(1.0)
                            success = self.bd_cli.set_main_display(self.config.virtual_display_name)
                    elif target_name == "physical":
                        if actual.physical_displays:
                            phys_spec = actual.physical_displays[0].uuid or actual.physical_displays[0].name
                            success = self.bd_cli.set_main_display(phys_spec)
                        else:
                            success = False
                    if not success:
                        self.runtime.last_error = f"Could not activate main display: {target_name}. Keeping fallback connected."

                self.runtime.transition_state = (TransitionState.COOLDOWN if self.runtime.cooldown_until > time.time() else TransitionState.IDLE)

                # Re-observe to update ActualState
                fresh_actual = self._observe()
                self.desired = self.policy(fresh_actual, self.config, self.runtime)
                sat = self.is_satisfied(self.actual, self.desired)
                # Keep the fallback connected: removing it coincided with Sidecar
                # session termination during headless boot. iPad remains main.
                if success and sat and self.runtime.cooldown_until <= time.time():
                    self.runtime.last_error = None
                self._export_status(satisfied=sat)

                if not success and self.desired.target_display_role != target_role and not sat:
                    # Activate fallback immediately after exhausting connection retries.
                    continue
                if not self.runtime.dirty or sat:
                    break

    def _determine_icon(self, satisfied: bool) -> str:
        if self.runtime.cooldown_until > time.time() or self.runtime.last_error:
            return IconStatus.WARNING.value
        if self.runtime.mode == OperationMode.MANUAL_ONLY:
            return IconStatus.PAUSED.value

        if self.actual:
            if self.actual.sidecar_connected:
                return IconStatus.IPAD.value
            if len(self.actual.physical_displays) > 0:
                return IconStatus.PHYSICAL.value
            if self.actual.virtual_display_connected:
                return IconStatus.VIRTUAL.value

        return IconStatus.VIRTUAL.value

    def _export_status(self, satisfied: bool) -> None:
        """Atomically persist status snapshot and ping SwiftBar."""
        if not self.actual or not self.desired:
            return

        icon = self._determine_icon(satisfied)
        actual_main_str = self.actual.main_display.name if self.actual.main_display else "None"
        physical_desc = (
            ", ".join(d.name for d in self.actual.physical_displays)
            if self.actual.physical_displays
            else "None"
        )

        status_details = {
            "physical_display": physical_desc,
            "usb_ipad": "Connected" if self.actual.ipad_usb_present else "Not Connected",
            "sidecar": "Connected" if self.actual.sidecar_connected else "Disconnected",
            "current_main": actual_main_str,
            "desired_role": self.desired.target_display_role.value,
            "actual_role_satisfied": "✓ Satisfied" if satisfied else "In Progress...",
            "reason": self.desired.reason,
            "generation": str(self.runtime.topology_generation),
            "virtual_display_name": self.config.virtual_display_name,
        }

        snapshot = StatusSnapshot(
            timestamp=time.time(),
            mode=self.runtime.mode.value,
            icon=icon,
            actual=self.actual.to_dict(),
            desired=self.desired.to_dict(),
            runtime=self.runtime.to_dict(),
            configured_ipad=self.config.ipad.to_dict(),
            paired_ipads=[ipad.to_dict() for ipad in self.config.paired_ipads],
            summary_text=f"{icon} PadPilot | {self.runtime.mode.value.title()}",
            status_details=status_details,
        )

        write_atomic_status(snapshot)
        self._notify_swiftbar()

    def _notify_swiftbar(self) -> None:
        """Trigger instant SwiftBar UI refresh via URL scheme."""
        from core.autostart import notify_swiftbar
        notify_swiftbar(self.config.swiftbar_plugin_id)
