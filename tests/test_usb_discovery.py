"""USB events and transient discovery use the existing engine and settings path."""
import contextlib
import io
import json
import runpy
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.config import Config
from core.detector import DisplayDetector
from core.models import ActualState, DisplayInfo, DisplayRole, IpadConfig, OperationMode, UserOverride
from core.settings import apply_change
from core.state_engine import StateEngine
from core.usb_events import USBEventMonitor

ROOT = Path(__file__).resolve().parents[1]
DAEMON = runpy.run_path(str(ROOT / 'bin/padpilotd'))
CLI = runpy.run_path(str(ROOT / 'bin/padpilot-cli'))
MENU = runpy.run_path(str(ROOT / 'core/menu.py'))
UUID = '11111111-1111-4111-8111-111111111111'
USB = {'vendor_id': 1452, 'product_name': 'iPad', 'serial': 'usb1'}
DEVICE = {'name': 'Live iPad', 'uuid': UUID}


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(auto_detect_ipad=True)
        self.bd = MagicMock(sidecar_error='', connection_error='', identifiers_error='')
        self.bd.check_virtual_display.return_value = (True, True)
        self.bd.get_sidecar_list.return_value = [DEVICE]
        self.bd.get_sidecar_connected.return_value = False
        self.detector = DisplayDetector(self.cfg, self.bd)
        self.detector.get_online_displays = MagicMock(return_value=[])
        self.detector.parse_usb_devices = MagicMock(return_value=[USB])

    def test_unique_candidate_is_ephemeral_and_identity_changes_generation(self):
        before = self.cfg.to_dict()
        actual, signature = self.detector.observe()
        self.assertEqual(actual.resolved_ipad, IpadConfig('Live iPad', UUID, 'usb1'))
        self.assertTrue(actual.ipad_usb_present and actual.sidecar_available)
        self.assertEqual(self.cfg.to_dict(), before)
        self.bd.get_sidecar_list.return_value = [dict(DEVICE, uuid='other')]
        _, changed = self.detector.observe()
        self.assertNotEqual(signature, changed)

    def test_ambiguous_missing_and_partial_discovery_never_connect(self):
        cases = [([], [DEVICE], ''), ([USB, dict(USB, serial='usb2')], [DEVICE], ''),
                 ([USB], [], ''), ([USB], [DEVICE, dict(DEVICE, uuid='other')], ''),
                 ([USB], [DEVICE], 'partial response'),
                 ([dict(USB, serial=None)], [DEVICE], '')]
        for usbs, candidates, error in cases:
            with self.subTest(usbs=usbs, candidates=candidates, error=error):
                self.detector.parse_usb_devices.return_value = usbs
                self.bd.get_sidecar_list.return_value = candidates
                self.bd.sidecar_error = error
                actual, _ = self.detector.observe()
                self.assertFalse(actual.sidecar_available)
                self.assertFalse(actual.resolved_ipad.sidecar_uuid)
                self.assertIn('auto_detect', actual.discovery_errors)
                engine = StateEngine(self.cfg, self.detector, self.bd)
                engine.runtime.user_override = UserOverride(DisplayRole.IPAD_MAIN, 0)
                self.assertFalse(engine.policy(actual, self.cfg, engine.runtime).needs_sidecar_connect)
                self.assertFalse(engine.reconnect_sidecar())
        self.bd.connect_sidecar.assert_not_called()
        self.bd.disconnect_sidecar.assert_not_called()

    def test_known_usb_resolves_saved_uuid_and_disabled_preserves_explicit_target(self):
        saved = IpadConfig('My label', UUID, 'usb1')
        self.cfg.paired_ipads = [saved]
        self.bd.get_sidecar_list.return_value = [dict(DEVICE, uuid='other'), DEVICE]
        actual, _ = self.detector.observe()
        self.assertEqual(actual.resolved_ipad.sidecar_uuid, UUID)
        self.cfg.ipad = saved
        self.cfg.auto_detect_ipad = False
        self.detector.parse_usb_devices.return_value = []
        actual, _ = self.detector.observe()
        self.assertEqual(actual.resolved_ipad, saved)
        self.assertTrue(actual.sidecar_available)

    def test_explicit_pairing_survives_usb_unplug_and_wireless_discovery_loss(self):
        saved = IpadConfig('My label', UUID, 'usb1')
        self.cfg.ipad = saved
        before = self.cfg.to_dict()
        self.bd.get_sidecar_connected.return_value = True
        screen = DisplayInfo(5, DEVICE['name'], uuid='display-uuid', is_sidecar=True, is_main=True)
        self.detector.get_online_displays.return_value = [screen]
        for usbs, candidates in (([USB], [DEVICE]), ([], [DEVICE]),
                                 ([dict(USB, serial='other')], [DEVICE, dict(DEVICE, uuid='other')]),
                                 ([], [])):
            with self.subTest(usbs=usbs, candidates=candidates):
                self.detector.parse_usb_devices.return_value = usbs
                self.bd.get_sidecar_list.return_value = candidates
                actual, _ = self.detector.observe()
                self.assertEqual(actual.resolved_ipad, saved)
                self.assertNotIn('auto_detect', actual.discovery_errors)
                self.assertTrue(actual.sidecar_connected)
                self.assertTrue(actual.sidecar_display_online)
                self.assertEqual(actual.sidecar_display_id, screen.display_id)
                self.bd.get_sidecar_connected.assert_called_with(UUID)
                engine = StateEngine(self.cfg, self.detector, self.bd)
                desired = engine.policy(actual, self.cfg, engine.runtime)
                self.assertEqual(desired.target_display_role, DisplayRole.IPAD_MAIN)
                self.assertFalse(desired.needs_sidecar_disconnect)
                self.assertFalse(desired.needs_sidecar_connect)
                self.assertTrue(engine.is_satisfied(actual, desired))
                engine._export_status = MagicMock()
                engine.evaluate(async_transition=False)
                self.bd.connect_sidecar.assert_not_called()
                self.bd.set_main_display.assert_not_called()
                engine._set_main_display(actual, 'ipad')
                self.bd.set_main_display.assert_called_once_with('display-uuid')
                self.bd.set_main_display.reset_mock()
        self.assertEqual(self.cfg.to_dict(), before)
        self.bd.get_sidecar_connected.return_value = False
        self.bd.get_sidecar_list.return_value = [DEVICE]
        self.detector.get_online_displays.return_value = []
        actual, _ = self.detector.observe()
        self.assertFalse(actual.ipad_usb_present)
        self.assertTrue(actual.sidecar_available)
        engine = StateEngine(self.cfg, self.detector, self.bd)
        self.assertTrue(engine.policy(actual, self.cfg, engine.runtime).needs_sidecar_connect)

    def test_usb_only_pairing_still_uses_discovery(self):
        self.cfg.ipad = IpadConfig('USB only', '', 'usb1')
        actual, _ = self.detector.observe()
        self.assertEqual(actual.resolved_ipad.sidecar_uuid, UUID)
        self.assertEqual(self.cfg.ipad.sidecar_uuid, '')

    def test_selected_uuid_flows_through_connect_and_main_display(self):
        actual, signature = self.detector.observe()
        screen = DisplayInfo(5, DEVICE['name'], uuid='display-uuid', is_sidecar=True)
        connected = ActualState(resolved_ipad=actual.resolved_ipad, sidecar_connected=True,
                                sidecar_display_online=True, sidecar_available=True,
                                sidecar_devices=[DEVICE], online_displays=[screen])
        self.detector.observe = MagicMock(side_effect=[(actual, signature), (connected, signature), (connected, signature)])
        engine = StateEngine(self.cfg, self.detector, self.bd)
        engine._export_status = MagicMock()
        with patch('core.state_engine.time.sleep'):
            engine.evaluate(async_transition=False)
        self.bd.connect_sidecar.assert_called_once_with(UUID)
        self.bd.set_main_display.assert_called_once_with('display-uuid')

    def test_manual_pause_physical_priority_and_cooldown_remain(self):
        actual, _ = self.detector.observe()
        engine = StateEngine(self.cfg, self.detector, self.bd)
        engine.runtime.mode = OperationMode.MANUAL_ONLY
        self.assertEqual(engine.policy(actual, self.cfg, engine.runtime).target_display_role, DisplayRole.NO_CHANGE)
        engine.runtime.mode = OperationMode.AUTOMATIC
        actual.physical_displays = [DisplayInfo(1, 'Monitor')]
        self.assertEqual(engine.policy(actual, self.cfg, engine.runtime).target_display_role, DisplayRole.PHYSICAL)
        actual.physical_displays = []
        engine.runtime.cooldown_until = time.time() + 20
        self.assertFalse(engine.policy(actual, self.cfg, engine.runtime).needs_sidecar_connect)

    def test_menu_uses_ephemeral_target_without_inventing_a_saved_pairing(self):
        actual, _ = self.detector.observe()
        model = MENU['render']({'actual': actual.to_dict(), 'config_revision': 1}, self.cfg.to_dict(), True)
        titles = [row['title'] for row in model['items']]
        self.assertIn('自動偵測目標：Live iPad', titles)
        self.assertIn('自動偵測中；不會儲存推定配對', titles)
        row = next(row for row in model['items'] if row['title'] == '設為主螢幕')
        self.assertEqual(row['args'], ['action', 'use_ipad_main'])
        self.assertTrue(row['enabled'])


class EventSettingsTests(unittest.TestCase):
    def test_setting_validation_roundtrip_and_cli_dispatch(self):
        cfg = Config()
        self.assertTrue(cfg.usb_event_wakeup)
        self.assertTrue(cfg.auto_detect_ipad)
        for field in ('usb_event_wakeup', 'auto_detect_ipad'):
            self.assertTrue(getattr(Config.from_dict({}), field))
            self.assertFalse(getattr(Config.from_dict({field: False}), field))
            action = 'set_' + field
            value = not getattr(cfg, field)
            self.assertTrue(apply_change(cfg, action, {'enabled': value}))
            self.assertEqual(getattr(Config.from_dict(cfg.to_dict()), field), value)
            for invalid in ('true', 1, None):
                with self.assertRaises(ValueError):
                    apply_change(cfg, action, {'enabled': invalid})
            handler = CLI['main']
            submit = MagicMock()
            with patch.dict(handler.__globals__, submit_settings=submit), \
                 patch.object(sys, 'argv', ['padpilot-cli', 'change-settings', action]), \
                 patch('sys.stdin', io.StringIO(json.dumps({'enabled': value}))):
                handler()
            self.assertEqual(submit.call_args.args[:2], (action, {'enabled': value}))

    def test_daemon_usb_toggle_does_not_reset_manual_override(self):
        daemon = DAEMON['PadPilotDaemon'].__new__(DAEMON['PadPilotDaemon'])
        daemon.config = Config()
        daemon.engine = MagicMock()
        daemon.detector = MagicMock()
        daemon.wakeup = threading.Event()
        daemon.usb_monitor = MagicMock()
        daemon.usb_monitor_enabled = False
        daemon.sync_usb_monitor()
        daemon.usb_monitor.start.assert_called_once()
        with patch.dict(daemon.apply_config_change.__func__.__globals__, save_config=MagicMock()):
            response = json.loads(daemon.handle_client_cmd(json.dumps({
                'command': 'set_usb_event_wakeup', 'params': {'enabled': False}, 'expected_revision': 1})))
        self.assertTrue(response['ok'])
        self.assertTrue(daemon.wakeup.is_set())
        daemon.sync_usb_monitor()
        daemon.usb_monitor.stop.assert_called_once()
        daemon.engine.reset_automation.assert_not_called()

    def test_event_wakes_existing_loop_and_stop_cleans_monitor(self):
        daemon = DAEMON['PadPilotDaemon'].__new__(DAEMON['PadPilotDaemon'])
        daemon.running = True
        daemon.config = Config()
        daemon.wakeup = threading.Event()
        daemon.usb_monitor = MagicMock(error='')
        daemon.usb_monitor_enabled = False
        daemon.detector = MagicMock()
        daemon.bd_cli = MagicMock()
        daemon.bd_cli.ensure_virtual_display.return_value = (True, 'OK')
        daemon.ensure_betterdisplay_running = MagicMock()
        daemon.engine = MagicMock()
        daemon.engine.runtime.debounce_until = 0
        def evaluate(trigger):
            if trigger == 'startup':
                daemon.wakeup.set()
            else:
                self.assertEqual(trigger, 'usb_event')
                daemon.stop()
        daemon.engine.evaluate.side_effect = evaluate
        with patch.dict(daemon.start.__func__.__globals__, remove_state_file=MagicMock()), \
             patch('threading.Thread'):
            with patch.dict(daemon.start.__func__.__globals__, open_menu_app=MagicMock()):
                daemon.start()
        self.assertEqual(daemon.engine.evaluate.call_count, 2)
        daemon.usb_monitor.stop.assert_called_once()

    def test_native_failure_is_reported_and_wakes_watchdog(self):
        event = threading.Event()
        monitor = USBEventMonitor(event.set)
        with patch('core.usb_events.C.CDLL', side_effect=OSError('unavailable')):
            monitor.start()
            self.assertTrue(monitor.ready.wait(3))
            monitor.stop()
        self.assertTrue(event.is_set())
        self.assertIn('Watchdog', monitor.error)
        self.assertFalse(monitor.thread.is_alive())

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS IOKit only')
    def test_native_registration_shutdown_and_restart(self):
        monitor = USBEventMonitor(threading.Event().set)
        try:
            for _ in range(2):
                monitor.start()
                self.assertTrue(monitor.ready.wait(3))
                self.assertEqual(monitor.error, '')
                self.assertTrue(monitor.thread.is_alive())
                monitor.stop()
                self.assertFalse(monitor.thread.is_alive())
        finally:
            monitor.stop()


if __name__ == '__main__':
    unittest.main()
