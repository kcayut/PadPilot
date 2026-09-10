"""Boot and conflicting-policy regressions; never operate the real displays."""
import runpy
import socket
import subprocess
import ctypes
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
        self.cfg = Config(auto_detect_ipad=False, ipad=IpadConfig(name="Target iPad", sidecar_uuid="TARGET"), retry_interval=0)
        self.bd = MagicMock(spec=BetterDisplayCLI)
        self.detector = MagicMock(spec=DisplayDetector)
        self.engine = StateEngine(self.cfg, self.detector, self.bd)
        self.physical = DisplayInfo(1, "ROG PG279Q", is_main=True)
        self.virtual = DisplayInfo(99, "PadPilotVirtual", is_main=True, is_virtual=True)
        self.ipad = DisplayInfo(2, "Target iPad", is_main=True, is_sidecar=True)
        self.detector.observe.return_value = (ActualState(), ((), False))
        for target in ("core.state_engine.write_atomic_status", "core.state_engine.notify_error",
                       "core.state_engine.time.sleep"):
            mock = patch(target)
            mock.start()
            self.addCleanup(mock.stop)

    def test_report_headless_boot_and_real_monitor_priority(self):
        detector = DisplayDetector(self.cfg, self.bd)
        self.bd.check_virtual_display.return_value = (True, False)
        self.bd.get_sidecar_list.return_value = [{"uuid": "TARGET"}]
        for name, expected in [("Generic Display", DisplayRole.IPAD_MAIN),
                               ("ROG PG279Q", DisplayRole.PHYSICAL)]:
            connected = []
            monitor = DisplayInfo(1, name, is_main=True, width=1280, height=720)
            self.bd.get_sidecar_connected.side_effect = lambda _: bool(connected)
            self.bd.connect_sidecar.side_effect = lambda _: connected.append(True) or True
            with self.subTest(name=name), patch.object(detector, "get_online_displays", side_effect=lambda:
                [monitor, self.ipad] if connected else [monitor]
            ), patch.object(detector, "parse_usb_devices", return_value=[]):
                self.engine.detector = detector
                self.engine.actual = None
                self.engine._last_valid_actual = None
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

    def test_disconnect_and_reconnect_keep_ipad_if_fallback_fails(self):
        self.cfg.mode = self.engine.runtime.mode = OperationMode.MANUAL_ONLY
        actual = ActualState(main_display=self.ipad, sidecar_connected=True, sidecar_display_online=True)
        self.detector.observe.return_value = (actual, ((), False))
        for connect_ok, main_ok in ((False, False), (True, False), (True, True)):
            self.bd.connect_virtual_display.return_value = connect_ok
            self.bd.set_main_display.return_value = main_ok
            for action in ("disconnect", "reconnect"):
                with self.subTest(action=action, connect_ok=connect_ok, main_ok=main_ok):
                    if action == "disconnect":
                        self.engine.set_user_override(DisplayRole.IPAD_DISCONNECTED, async_transition=False)
                    else:
                        self.assertFalse(self.engine.reconnect_sidecar())
                    self.bd.disconnect_sidecar.assert_not_called()
                    self.assertTrue(self.engine.actual.sidecar_connected)
                    self.assertIsNotNone(self.engine.runtime.last_error)

    def test_disconnect_verifies_fallback_before_cutting_sidecar(self):
        self.cfg.mode = OperationMode.MANUAL_ONLY
        for action in ("disconnect", "reconnect"):
            for fallback in (self.virtual, self.physical):
                with self.subTest(action=action, fallback=fallback.name):
                    self.bd.reset_mock()
                    physicals = [self.physical] if fallback is self.physical else []
                    signature = (tuple(d.display_id for d in physicals), False)
                    actual = ActualState(main_display=self.ipad, physical_displays=physicals,
                                         sidecar_connected=True, sidecar_display_online=True)
                    self.detector.observe.return_value = (actual, signature)
                    engine = StateEngine(self.cfg, self.detector, self.bd)
                    def set_main(_):
                        actual.main_display = fallback
                        actual.virtual_display_connected = fallback is self.virtual
                        return True
                    def disconnect(specifier):
                        self.assertEqual(specifier, "TARGET")
                        self.assertEqual(engine.actual.main_display, fallback)
                        actual.sidecar_connected = actual.sidecar_display_online = False
                        return True
                    self.bd.set_main_display.side_effect = set_main
                    self.bd.disconnect_sidecar.side_effect = disconnect
                    with patch.object(engine, "_trigger_transition"):
                        if action == "disconnect":
                            engine.set_user_override(DisplayRole.IPAD_DISCONNECTED, async_transition=False)
                        else:
                            self.assertTrue(engine.reconnect_sidecar())
                    calls = [entry[0] for entry in self.bd.mock_calls]
                    self.assertLess(calls.index("set_main_display"), calls.index("disconnect_sidecar"))
                    self.bd.disconnect_sidecar.assert_called_once_with("TARGET")

    def test_usb_query_failure_preserves_disconnect_until_real_unplug(self):
        self.cfg.auto_detect_ipad = True
        self.cfg.ipad.usb_serial = "USB123"
        detector = DisplayDetector(self.cfg, self.bd)
        detector.get_online_displays = MagicMock(return_value=[self.virtual])
        self.bd.check_virtual_display.return_value = (True, True)
        self.bd.get_sidecar_list.return_value = [{"name": "Target iPad", "uuid": "TARGET"}]
        self.bd.get_sidecar_connected.return_value = False
        self.engine.detector = detector
        with patch.object(detector, "parse_usb_devices", return_value=[
            {"vendor_id": 1452, "serial": "USB123"}
        ]):
            self.engine.set_user_override(DisplayRole.IPAD_DISCONNECTED, async_transition=False)
        generation = self.engine.runtime.topology_generation
        with patch("core.detector.subprocess.check_output", side_effect=subprocess.TimeoutExpired("ioreg", 3)):
            self.engine.evaluate(async_transition=False)
        self.assertIn("usb", self.engine.actual.discovery_errors)
        self.assertEqual(self.engine.runtime.topology_generation, generation)
        self.assertIsNotNone(self.engine.runtime.user_override)
        self.bd.connect_sidecar.assert_not_called()
        detector.usb_error = ""
        with patch.object(detector, "parse_usb_devices", return_value=[
            {"vendor_id": 1452, "serial": "USB123"}
        ]):
            self.engine.evaluate(async_transition=False)
        self.assertEqual(self.engine.runtime.topology_generation, generation)
        self.assertIsNotNone(self.engine.runtime.user_override)
        with patch("core.detector.subprocess.check_output", return_value=""), \
             patch.object(self.engine, "_trigger_transition"):
            self.engine.evaluate()
        self.assertEqual(self.engine.runtime.topology_generation, generation + 1)
        self.assertIsNone(self.engine.runtime.user_override)
        self.assertTrue(self.engine.desired.needs_sidecar_connect)

    def test_accepted_connection_without_display_reaches_cooldown(self):
        actual = ActualState(main_display=self.virtual, virtual_display_connected=True, sidecar_available=True)
        self.detector.observe.return_value = (actual, ((), False))
        self.bd.connect_sidecar.return_value = True
        self.bd.set_main_display.return_value = False
        self.engine.evaluate(async_transition=False)
        self.assertEqual(self.bd.connect_sidecar.call_count, self.cfg.max_retries)
        self.assertGreater(self.engine.runtime.cooldown_until, time.time())
        self.bd.set_main_display.assert_not_called()
        self.engine.evaluate(async_transition=False)
        self.assertEqual(self.bd.connect_sidecar.call_count, self.cfg.max_retries)

    def test_late_display_is_verified_without_duplicate_connection(self):
        self.cfg.retry_interval = 3
        before = ActualState(main_display=self.virtual, virtual_display_connected=True, sidecar_available=True)
        session_only = ActualState(main_display=self.virtual, virtual_display_connected=True,
                                   sidecar_available=True, sidecar_connected=True)
        ready = ActualState(main_display=self.ipad, virtual_display_connected=True,
                            sidecar_connected=True, sidecar_display_online=True)
        self.detector.observe.side_effect = [(s, ((), False)) for s in (before, session_only, ready, ready)]
        self.bd.connect_sidecar.return_value = True
        with patch("core.state_engine.time.monotonic", side_effect=[0, 0, 1]):
            self.engine.evaluate(async_transition=False)
        self.bd.connect_sidecar.assert_called_once_with("TARGET")
        self.assertEqual(self.engine.runtime.retry_count, 0)
        self.assertEqual(self.engine.runtime.cooldown_until, 0)
        self.assertTrue(self.engine.is_satisfied(self.engine.actual, self.engine.desired))

    def test_connected_session_without_display_also_obeys_cooldown(self):
        actual = ActualState(main_display=self.virtual, virtual_display_connected=True, sidecar_connected=True)
        self.detector.observe.return_value = (actual, ((), False))
        self.engine.evaluate(async_transition=False)
        self.assertGreater(self.engine.runtime.cooldown_until, time.time())
        self.bd.connect_sidecar.assert_not_called()
        self.bd.set_main_display.assert_not_called()

    def test_unknown_connection_query_never_confirms_or_reissues_connection(self):
        before = ActualState(sidecar_available=True)
        unknown = ActualState(sidecar_connected=True, sidecar_display_online=True,
                              discovery_errors={"sidecar_connection": "timeout"})
        self.detector.observe.side_effect = [(s, ((), False)) for s in (before, unknown, unknown)]
        self.bd.connect_sidecar.return_value = True
        self.engine.evaluate(async_transition=False)
        self.assertEqual(self.engine.runtime.retry_count, 1)
        self.assertEqual(self.engine.desired.target_display_role, DisplayRole.NO_CHANGE)
        self.bd.connect_sidecar.assert_called_once_with("TARGET")
        self.bd.set_main_display.assert_not_called()

    def test_failed_display_scan_does_not_expire_override_or_erase_debounce_history(self):
        before = ActualState(main_display=self.physical, physical_displays=[self.physical])
        failed = ActualState(discovery_errors={"displays": "timeout"})
        unplugged = ActualState(sidecar_available=True)
        self.detector.observe.side_effect = [(before, ((1,), False)), (failed, ((), False)),
                                            (unplugged, ((), False))]
        self.engine._observe()
        self.engine.runtime.user_override = UserOverride(DisplayRole.IPAD_MAIN, 0)
        self.engine.evaluate(async_transition=False)
        self.assertIsNotNone(self.engine.runtime.user_override)
        self.assertEqual(self.engine.runtime.topology_generation, 0)
        self.engine.evaluate(async_transition=False)
        self.assertIsNone(self.engine.runtime.user_override)
        self.assertEqual(self.engine.runtime.topology_generation, 1)
        self.assertGreater(self.engine.runtime.debounce_until, time.time())
        self.bd.connect_sidecar.assert_not_called()

    def test_saved_ipad_label_cannot_classify_a_physical_display(self):
        self.cfg.ipad.name = "Office"
        self.bd.check_virtual_display.return_value = (True, False)
        self.bd.get_sidecar_list.return_value = []
        self.bd.get_sidecar_connected.return_value = False
        detector = DisplayDetector(self.cfg, self.bd)
        for name in ("Office Monitor", "Office", "iPad Workstation", "Sidecar Monitor"):
            with self.subTest(name=name):
                monitor = DisplayInfo(1, name, is_main=True)
                with patch.object(detector, "get_online_displays", return_value=[monitor]), \
                     patch.object(detector, "parse_usb_devices", return_value=[]):
                    actual, _ = detector.observe()
                self.assertEqual(actual.physical_displays, [monitor])
                self.assertFalse(monitor.is_sidecar)
                self.assertEqual(self.engine.policy(actual, self.cfg, self.engine.runtime).target_display_role,
                                 DisplayRole.PHYSICAL)

    def test_sidecar_hardware_identity_does_not_depend_on_display_name(self):
        detector = DisplayDetector(self.cfg, self.bd)
        def display_list(_, ids, count):
            ids[0] = 7
            ctypes.cast(count, ctypes.POINTER(ctypes.c_uint32))[0] = 1
            return 0
        detector._cg = MagicMock()
        detector._cg.CGGetOnlineDisplayList.side_effect = display_list
        detector._cg.CGDisplayIsActive.return_value = 1
        detector._cg.CGDisplayPixelsWide.return_value = 1920
        detector._cg.CGDisplayPixelsHigh.return_value = 1080
        detector._cg.CGDisplayModelNumber.return_value = 1
        for name, vendor, expected in (("iPad Monitor", 1234, False), ("Sidecar Monitor", 1234, False),
                                       ("Office", 0x6161706C, True)):
            with self.subTest(name=name, vendor=vendor):
                detector._cg.CGDisplayVendorNumber.return_value = vendor
                self.bd.get_display_identifiers.return_value = [{"displayID": "7", "name": name}]
                displays = detector.get_online_displays()
                self.assertEqual(len(displays), 1)
                self.assertEqual(displays[0].is_sidecar, expected)

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

    def test_secondary_with_virtual_main_is_not_satisfied_when_physical_returns(self):
        actual = ActualState(physical_displays=[self.physical], main_display=self.virtual,
                             virtual_display_connected=True, sidecar_connected=True, sidecar_display_online=True)
        desired = self.engine.policy(actual, self.cfg, self.engine.runtime)
        self.assertEqual(desired.target_display_role, DisplayRole.IPAD_SECONDARY)
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

    def test_successful_main_switch_keeps_fallback_and_clears_error(self):
        before = ActualState(main_display=self.virtual, virtual_display_connected=True,
                             sidecar_connected=True, sidecar_display_online=True)
        after = ActualState(main_display=self.ipad, virtual_display_connected=True,
                            sidecar_connected=True, sidecar_display_online=True)
        self.detector.observe.side_effect = [(before, ((), False)), (after, ((), False))]
        self.engine.runtime.last_error = "Previous failure"
        self.engine.evaluate(async_transition=False)
        self.bd.disconnect_virtual_display.assert_not_called()
        self.assertTrue(self.engine.actual.virtual_display_connected)
        self.assertEqual(self.engine.actual.main_display, self.ipad)
        self.assertIsNone(self.engine.runtime.last_error)

    def test_headless_connect_keeps_virtual_fallback_online(self):
        before = ActualState(virtual_display_exists=True, sidecar_available=True)
        after = ActualState(main_display=self.ipad, virtual_display_exists=True,
                            virtual_display_connected=True, sidecar_connected=True,
                            sidecar_display_online=True)
        self.detector.observe.side_effect = [(before, ((), False)), (after, ((), False)), (after, ((), False))]
        self.engine.evaluate(async_transition=False)
        names = [entry[0] for entry in self.bd.mock_calls]
        self.assertLess(names.index("connect_virtual_display"), names.index("connect_sidecar"))
        self.bd.disconnect_virtual_display.assert_not_called()
        self.assertTrue(self.engine.is_satisfied(self.engine.actual, self.engine.desired))

    def test_manual_disconnect_is_not_undone_by_prefer_ipad(self):
        before = ActualState(physical_displays=[self.physical], main_display=self.physical,
                             sidecar_available=True, sidecar_connected=True, sidecar_display_online=True)
        after = ActualState(physical_displays=[self.physical], main_display=self.physical, sidecar_available=True)
        self.engine.runtime.mode = OperationMode.PREFER_IPAD
        self.detector.observe.side_effect = [(before, ((1,), False)), (before, ((1,), False)),
                                            (after, ((1,), False)), (after, ((1,), False))]
        self.engine.set_user_override(DisplayRole.IPAD_DISCONNECTED, async_transition=False)
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
