"""Boot and conflicting-policy regressions; never operate the real displays."""
import runpy
import socket
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.betterdisplay import BetterDisplayCLI
from core.config import Config
from core.detector import DisplayDetector
from core.models import ActualState, DisplayInfo, DisplayRole, IpadConfig, OperationMode, UserOverride
from core.state_engine import StateEngine


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(ipad=IpadConfig(name="Target iPad", sidecar_uuid="TARGET"), retry_interval=0)
        self.bd = MagicMock(spec=BetterDisplayCLI)
        self.detector = MagicMock(spec=DisplayDetector)
        self.engine = StateEngine(self.cfg, self.detector, self.bd)
        self.physical = DisplayInfo(1, "ROG PG279Q", is_main=True)
        self.virtual = DisplayInfo(99, "PadPilotVirtual", is_main=True, is_virtual=True)
        self.ipad = DisplayInfo(2, "Target iPad", is_main=True, is_sidecar=True)
        self.detector.observe.return_value = (ActualState(), ((), False))
        for target in ("core.state_engine.write_atomic_status", "core.state_engine.notify_error",
                       "core.state_engine.StateEngine._notify_swiftbar", "core.state_engine.time.sleep"):
            mock = patch(target)
            mock.start()
            self.addCleanup(mock.stop)

    def test_report_headless_boot_and_real_monitor_priority(self):
        detector = DisplayDetector(self.cfg, self.bd)
        self.bd.check_virtual_display.return_value = (True, False)
        self.bd.get_sidecar_list.return_value = [{"uuid": "TARGET"}]
        for name, expected in [("Generic Display", DisplayRole.IPAD_MAIN),
                               ("ROG PG279Q", DisplayRole.PHYSICAL)]:
            with self.subTest(name=name), patch.object(detector, "get_online_displays", return_value=[
                DisplayInfo(1, name, is_main=True, width=1280, height=720)
            ]), patch.object(detector, "parse_usb_devices", return_value=[]):
                self.engine.detector = detector
                self.engine.actual = None
                self.engine.runtime.last_topology_signature = None
                self.engine.runtime.debounce_until = 0
                self.engine.evaluate("startup", async_transition=False)
                self.assertEqual(self.engine.desired.target_display_role, expected)
        self.bd.connect_sidecar.assert_called_once_with("TARGET")
        self.bd.set_main_display.assert_called_once_with("Target iPad")

    def test_empty_ignore_patterns_do_not_hide_physical_monitor(self):
        self.cfg.virtual_display_name = ""
        self.cfg.ignore_list = [""]
        detector = DisplayDetector(self.cfg, self.bd)
        self.assertFalse(detector.is_display_ignored(self.physical))
        self.assertFalse(detector.is_display_ignored(DisplayInfo(3, "Generic DisplayPort Monitor")))

    def test_cooldown_applies_to_all_modes_and_overrides(self):
        actual = ActualState(sidecar_available=True)
        for mode in OperationMode:
            for override in (None, DisplayRole.IPAD_MAIN, DisplayRole.IPAD_SECONDARY):
                with self.subTest(mode=mode, override=override):
                    self.engine.runtime.mode = mode
                    self.engine.runtime.user_override = UserOverride(override, 0) if override else None
                    self.engine.runtime.cooldown_until = time.time() + 30
                    desired = self.engine.policy(actual, self.cfg, self.engine.runtime)
                    self.assertFalse(desired.needs_sidecar_connect)

    def test_headless_connected_ipad_survives_discovery_disappearance(self):
        actual = ActualState(main_display=self.ipad, sidecar_connected=True, sidecar_display_online=True)
        for mode in (OperationMode.AUTOMATIC, OperationMode.PREFER_IPAD):
            self.engine.runtime.mode = mode
            desired = self.engine.policy(actual, self.cfg, self.engine.runtime)
            self.assertEqual(desired.target_display_role, DisplayRole.IPAD_MAIN)
            self.assertTrue(self.engine.is_satisfied(actual, desired))

    def test_physical_return_from_virtual_has_main_target(self):
        actual = ActualState(physical_displays=[self.physical], main_display=self.virtual,
                             virtual_display_connected=True)
        desired = self.engine.policy(actual, self.cfg, self.engine.runtime)
        self.assertFalse(self.engine.is_satisfied(actual, desired))
        self.assertEqual(desired.needs_main_display_target, "physical")

    def test_failed_or_unobserved_main_switch_keeps_fallback(self):
        actual = ActualState(main_display=self.virtual, virtual_display_connected=True,
                             sidecar_connected=True, sidecar_display_online=True)
        self.detector.observe.return_value = (actual, ((), False))
        for command_ok in (False, True):
            self.bd.set_main_display.return_value = command_ok
            self.engine.evaluate(async_transition=False)
            self.bd.disconnect_virtual_display.assert_not_called()

    def test_successful_main_switch_retires_fallback_and_clears_error(self):
        before = ActualState(main_display=self.virtual, virtual_display_connected=True,
                             sidecar_connected=True, sidecar_display_online=True)
        after = ActualState(main_display=self.ipad, virtual_display_connected=True,
                            sidecar_connected=True, sidecar_display_online=True)
        final = ActualState(main_display=self.ipad, sidecar_connected=True, sidecar_display_online=True)
        self.detector.observe.side_effect = [(before, ((), False)), (after, ((), False)), (final, ((), False))]
        self.engine.runtime.last_error = "Previous failure"
        self.engine.evaluate(async_transition=False)
        self.bd.disconnect_virtual_display.assert_called_once_with("PadPilotVirtual")
        self.assertIsNone(self.engine.runtime.last_error)

    def test_manual_disconnect_is_not_undone_by_prefer_ipad(self):
        before = ActualState(physical_displays=[self.physical], main_display=self.physical,
                             sidecar_available=True, sidecar_connected=True, sidecar_display_online=True)
        after = ActualState(physical_displays=[self.physical], main_display=self.physical, sidecar_available=True)
        self.engine.runtime.mode = OperationMode.PREFER_IPAD
        self.detector.observe.side_effect = [(before, ((1,), False)), (before, ((1,), False)),
                                            (after, ((1,), False)), (after, ((1,), False))]
        self.engine.set_user_override(DisplayRole.NO_CHANGE, async_transition=False)
        self.engine.evaluate(async_transition=False)
        self.bd.disconnect_sidecar.assert_called_once_with("TARGET")
        self.bd.connect_sidecar.assert_not_called()

    def test_topology_change_during_transition_expires_override(self):
        before = ActualState(physical_displays=[self.physical], main_display=self.physical)
        after = ActualState(sidecar_available=True)
        self.engine.actual = before
        self.engine.runtime.last_topology_signature = ((1,), False)
        self.engine.runtime.user_override = UserOverride(DisplayRole.IPAD_MAIN, 0)
        self.engine.desired = self.engine.policy(before, self.cfg, self.engine.runtime)
        self.detector.observe.return_value = (after, ((), False))
        self.engine._run_transition()
        self.assertEqual(self.engine.runtime.topology_generation, 1)
        self.assertIsNone(self.engine.runtime.user_override)
        self.assertGreater(self.engine.runtime.debounce_until, time.time())

    def test_mode_change_waits_for_inflight_transition(self):
        entered, release, changed = threading.Event(), threading.Event(), threading.Event()
        actual = ActualState(sidecar_available=True)
        self.detector.observe.return_value = (actual, ((), False))
        self.engine.actual = actual
        self.engine.desired = self.engine.policy(actual, self.cfg, self.engine.runtime)

        def connect(_):
            entered.set()
            release.wait(2)
            return True

        def change_mode():
            self.engine.set_mode(OperationMode.MANUAL_ONLY)
            changed.set()

        self.bd.connect_sidecar.side_effect = connect
        worker = threading.Thread(target=self.engine._run_transition)
        setter = threading.Thread(target=change_mode)
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            setter.start()
            self.assertFalse(changed.wait(0.05))
        finally:
            release.set()
            worker.join(2)
            if setter.ident:
                setter.join(2)
        self.assertTrue(changed.is_set())
        self.assertFalse(worker.is_alive())
        self.assertFalse(setter.is_alive())
        self.bd.reset_mock()
        self.engine.evaluate(async_transition=False)
        self.bd.set_main_display.assert_not_called()
        self.bd.connect_sidecar.assert_not_called()

    def test_reconnect_of_disconnected_ipad_does_not_require_disconnect_success(self):
        self.detector.observe.return_value = (ActualState(sidecar_available=True), ((), False))
        self.bd.disconnect_sidecar.return_value = False
        with patch.object(self.engine, "_trigger_transition"):
            self.assertTrue(self.engine.reconnect_sidecar())
        self.bd.disconnect_sidecar.assert_not_called()
        self.assertTrue(self.engine.desired.needs_sidecar_connect)

    def test_cli_timeout_never_unlinks_socket_or_reports_daemon_stopped(self):
        module = runpy.run_path(str(Path(__file__).resolve().parents[1] / "bin/padpilot-cli"))
        with patch("pathlib.Path.exists", return_value=True), patch("pathlib.Path.unlink") as unlink, \
             patch("socket.socket") as sock:
            sock.return_value.__enter__.return_value.recv.side_effect = socket.timeout()
            response = module["send_daemon_cmd"]("refresh")
            self.assertIn("timed out", response)
            self.assertNotIn("Daemon is not running", response)
            unlink.assert_not_called()

    def test_virtual_lookup_does_not_accept_someone_elses_virtual_screen(self):
        cli = BetterDisplayCLI.__new__(BetterDisplayCLI)
        with patch.object(cli, "get_display_identifiers", return_value=[
            {"name": "Unrelated", "deviceType": "VirtualScreen", "displayID": "99"},
            {"name": "PadPilotVirtual", "deviceType": "VirtualScreen", "displayID": None},
        ]):
            self.assertEqual(cli.check_virtual_display("PadPilotVirtual"), (True, False))
            self.assertEqual(cli.check_virtual_display("Missing"), (False, False))


if __name__ == "__main__":
    unittest.main()
