"""Boot requests are bounded; service restarts and later USB events do not re-arm them."""
import json
import runpy
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.config import Config, HOTKEY_NAMED_KEYS, validate_connection_hotkey
from core.models import ActualState, DisplayInfo, IpadConfig, OperationMode
from core.state_engine import StateEngine
from core.gui import MODES as GUI_MODES
from core.menu import MODES as MENU_MODES

Daemon = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'bin/padpilotd'))['PadPilotDaemon']


class BootConnectionTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(auto_detect_ipad=False, ipad=IpadConfig('iPad', 'TARGET'), retry_interval=0)
        self.actual = ActualState(sidecar_available=True, resolved_ipad=self.cfg.ipad)
        self.detector = MagicMock()
        self.detector.observe.side_effect = lambda **_: (self.actual, ((), self.actual.ipad_usb_present))
        self.bd = MagicMock()
        self.bd.connect_sidecar.return_value = False
        self.engine = StateEngine(self.cfg, self.detector, self.bd)
        self.engine.actual = self.actual
        self.daemon = Daemon.__new__(Daemon)
        self.daemon.engine, self.daemon.config = self.engine, self.cfg
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ('core.state_engine.write_atomic_status', 'core.state_engine.notify_error', 'core.state_engine.StateEngine._wait'):
            self.stack.enter_context(patch(target))

    def test_defaults_existing_preferences_order_and_setting_transaction(self):
        for config in (Config(), Config.from_dict({})):
            self.assertEqual(config.mode, OperationMode.MANUAL_ONLY)
            self.assertTrue(config.connect_on_boot)
        self.assertEqual(Config.from_dict({'mode': 'automatic'}).mode, OperationMode.AUTOMATIC)
        self.assertEqual(list(GUI_MODES), ['manual_only', 'automatic', 'prefer_ipad'])
        self.assertEqual(list(MENU_MODES), list(GUI_MODES))
        self.engine.runtime.retry_count = 3
        with patch.dict(self.daemon.apply_config_change.__globals__, save_config=lambda _: None):
            result = json.loads(self.daemon.handle_client_cmd(json.dumps({
                'command': 'set_connect_on_boot', 'expected_revision': 1, 'params': {'enabled': False}})))
        self.assertTrue(result['ok'])
        self.assertFalse(self.daemon.config.connect_on_boot)
        self.assertEqual(self.engine.runtime.retry_count, 3)
        self.detector.observe.assert_not_called()
        for bad in (0, 'true', None):
            with self.assertRaises(ValueError):
                Config.from_dict({'connect_on_boot': bad})
        for key in HOTKEY_NAMED_KEYS:
            self.assertEqual(validate_connection_hotkey('ctrl+cmd+' + key), 'ctrl+cmd+' + key)

    def test_boot_marker_survives_service_restarts_and_disabled_modes(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(self.daemon.claim_boot_connection.__globals__, APP_SUPPORT_DIR=Path(directory)), \
             patch('subprocess.check_output', return_value='11111111-1111-4111-8111-111111111111') as boot:
            self.assertTrue(self.daemon.claim_boot_connection())
            self.assertFalse(self.daemon.claim_boot_connection())
            boot.return_value = '22222222-2222-4222-8222-222222222222'
            self.cfg.connect_on_boot = False
            self.assertFalse(self.daemon.claim_boot_connection())
            self.cfg.connect_on_boot = True
            self.assertFalse(self.daemon.claim_boot_connection())
            boot.return_value = '33333333-3333-4333-8333-333333333333'
            self.assertTrue(self.daemon.claim_boot_connection())

    def test_discovery_wait_then_one_round_and_no_later_reconnection(self):
        deadline = time.monotonic() + 90
        self.actual.discovery_errors = {'sidecar_connection': 'Failed.'}
        self.assertTrue(self.daemon.try_boot_connection(deadline))
        self.bd.connect_sidecar.assert_not_called()
        self.actual.discovery_errors = {}
        with patch.object(self.engine, '_trigger_transition'):
            self.assertFalse(self.daemon.try_boot_connection(deadline))
        self.engine._run_transition()
        self.assertEqual(self.bd.connect_sidecar.call_count, 3)
        self.assertIsNone(self.engine.runtime.user_override)
        for present in (False, True, False, True):
            self.actual.ipad_usb_present = present
            self.actual.sidecar_available = present
            self.engine.evaluate('usb_event', async_transition=False)
            self.assertFalse(self.daemon.try_boot_connection(deadline))
        self.assertEqual(self.bd.connect_sidecar.call_count, 3)

    def test_startup_searches_three_rounds_then_stops_despite_usb_events(self):
        for arrival in (None, 36, 66, 96):
            with self.subTest(arrival=arrival):
                now, searches, requests = [0.0], [], []
                self.daemon.running = True
                self.daemon.wakeup = MagicMock()
                self.daemon.usb_monitor = MagicMock(error='')
                self.daemon.usb_monitor_enabled = False
                self.daemon.detector = self.detector
                self.daemon.bd_cli = MagicMock()
                self.daemon.bd_cli.ensure_virtual_display.return_value = (True, 'OK')
                self.daemon.ensure_betterdisplay_running = MagicMock()

                def wait(timeout):
                    now[0] += timeout
                    if now[0] >= 130:
                        self.daemon.running = False
                    return now[0] in (10, 40, 70, 88)  # Late USB wakeups must not buy another round.

                def observe(trigger):
                    searches.append(now[0])
                    self.actual.discovery_errors = ({} if arrival is not None and now[0] >= arrival
                                                    else {'sidecar_connection': 'Failed.'})

                self.daemon.wakeup.wait.side_effect = wait
                with patch.dict(self.daemon.start.__globals__, remove_state_file=MagicMock(), open_menu_app=MagicMock()), \
                     patch('threading.Thread'), patch('time.monotonic', side_effect=lambda: now[0]), \
                     patch.object(self.daemon, 'claim_boot_connection', return_value=True), \
                     patch.object(self.engine, 'evaluate', side_effect=observe), \
                     patch.object(self.engine, 'request_sidecar_connection', side_effect=lambda **_: requests.append(now[0])):
                    self.daemon.start()
                self.assertEqual(requests, [arrival] if arrival in (36, 66) else [])
                if arrival is None:
                    for tick in (0, 28, 30, 58, 60, 88, 90):
                        self.assertIn(tick, searches)
                self.daemon.usb_monitor.stop.assert_called_once()

    def test_deadline_physical_monitor_and_fresh_monitor_race_cancel(self):
        self.actual.discovery_errors = {'sidecar_connection': 'Failed.'}
        self.assertFalse(self.daemon.try_boot_connection(time.monotonic() - 1))
        self.actual.discovery_errors = {}
        monitor = DisplayInfo(1, 'Monitor', is_main=True)
        self.actual.physical_displays = [monitor]
        self.assertFalse(self.daemon.try_boot_connection(time.monotonic() + 30))
        self.engine.actual = ActualState(sidecar_available=True, resolved_ipad=self.cfg.ipad)
        self.assertFalse(self.daemon.try_boot_connection(time.monotonic() + 30))
        self.bd.connect_sidecar.assert_not_called()
        self.assertIsNone(self.engine.runtime.user_override)
