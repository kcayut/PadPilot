"""Shortcut requests use the real policy/transition path with simulated hardware."""
import argparse
import io
import json
from contextlib import ExitStack, redirect_stderr
import runpy
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.config import Config
from core.models import ActualState, DisplayInfo, DisplayRole, IpadConfig, OperationMode
from core.settings import apply_change
from core.i18n import set_language, tr_message
from core.state_engine import StateEngine


class ConnectionHotkeyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(mode=OperationMode.MANUAL_ONLY, auto_detect_ipad=False,
                          ipad=IpadConfig('iPad', 'TARGET'), retry_interval=0)
        self.bd = MagicMock()
        self.detector = MagicMock()
        self.fallback = DisplayInfo(99, 'PadPilotVirtual', is_main=True, is_virtual=True)
        self.ipad = DisplayInfo(2, 'iPad', is_main=True, is_sidecar=True)
        self.actual = ActualState(main_display=self.fallback, virtual_display_connected=True,
                                  sidecar_available=True, resolved_ipad=self.cfg.ipad)
        self.detector.observe.side_effect = lambda **_: (self.actual, ((), self.actual.ipad_usb_present))
        self.engine = StateEngine(self.cfg, self.detector, self.bd)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ('core.state_engine.write_atomic_status', 'core.state_engine.notify_error', 'core.state_engine.time.sleep'):
            self.stack.enter_context(patch(target))

    def connect(self, _):
        self.actual.sidecar_connected = self.actual.sidecar_display_online = True
        self.actual.main_display = self.ipad
        return True

    def test_manual_success_and_failure_never_reconnect_on_later_scans(self):
        for success in (True, False):
            with self.subTest(success=success):
                self.setUpState()
                self.bd.connect_sidecar.side_effect = self.connect if success else lambda _: False
                self.assertTrue(self.engine.request_sidecar_connection(async_transition=False))
                attempts = self.bd.connect_sidecar.call_count
                self.assertEqual(attempts, 1 if success else 3)
                self.assertIsNone(self.engine.runtime.user_override)
                self.actual.sidecar_connected = self.actual.sidecar_display_online = False
                self.actual.main_display = self.fallback
                for hour in range(25):
                    self.actual.sidecar_available = bool(hour % 2)
                    self.actual.ipad_usb_present = bool(hour % 2)
                    with patch('core.state_engine.time.time', return_value=2000000000 + hour * 3600):
                        self.engine.evaluate('usb_event', async_transition=False)
                self.assertEqual(self.bd.connect_sidecar.call_count, attempts)
                self.assertTrue(self.engine.request_sidecar_connection(async_transition=False))
                self.assertGreater(self.bd.connect_sidecar.call_count, attempts)

    def setUpState(self):
        self.bd.reset_mock()
        self.actual.sidecar_connected = self.actual.sidecar_display_online = False
        self.actual.main_display = self.fallback
        self.engine = StateEngine(self.cfg, self.detector, self.bd)

    def test_automatic_policy_survives_explicit_request(self):
        self.cfg.mode = self.engine.runtime.mode = OperationMode.AUTOMATIC
        self.bd.connect_sidecar.side_effect = self.connect
        self.engine.request_sidecar_connection(async_transition=False)
        self.assertIsNone(self.engine.runtime.user_override)
        self.actual.sidecar_connected = self.actual.sidecar_display_online = False
        self.actual.main_display = self.fallback
        self.engine.evaluate(async_transition=False)
        self.assertEqual(self.bd.connect_sidecar.call_count, 2)

    def test_repeated_presses_coalesce_and_connected_ipad_is_untouched(self):
        self.bd.connect_sidecar.side_effect = self.connect
        with patch.object(self.engine, '_trigger_transition') as transition:
            for _ in range(10):
                self.assertTrue(self.engine.request_sidecar_connection())
            transition.assert_called_once()
        self.engine._run_transition()
        self.assertIsNone(self.engine.runtime.user_override)
        for _ in range(5):
            self.engine.request_sidecar_connection(async_transition=False)
        self.bd.connect_sidecar.assert_called_once()
        self.bd.disconnect_sidecar.assert_not_called()

    def test_physical_monitor_uses_secondary_and_unknown_target_does_not_connect(self):
        self.actual.physical_displays = [DisplayInfo(1, 'Monitor', is_main=True)]
        with patch.object(self.engine, '_trigger_transition'):
            self.engine.request_sidecar_connection()
        self.assertEqual(self.engine.runtime.user_override.target_role, DisplayRole.IPAD_SECONDARY)
        self.engine.runtime.user_override = None
        self.actual.discovery_errors = {'sidecar': 'timeout'}
        self.assertFalse(self.engine.request_sidecar_connection(async_transition=False))
        self.bd.connect_sidecar.assert_not_called()

    def test_manual_menu_controls_also_end_and_exception_clears_request(self):
        self.bd.connect_sidecar.side_effect = self.connect
        self.engine.set_user_override(DisplayRole.IPAD_MAIN, async_transition=False)
        self.assertIsNone(self.engine.runtime.user_override)
        self.actual.sidecar_connected = self.actual.sidecar_display_online = False
        self.bd.connect_sidecar.side_effect = RuntimeError('unexpected failure')
        with self.assertRaises(RuntimeError):
            self.engine.request_sidecar_connection(async_transition=False)
        self.assertIsNone(self.engine.runtime.user_override)

    def test_hotkey_settings_are_validated_and_do_not_connect(self):
        self.assertEqual(Config.from_dict({}).connection_hotkey, '')
        self.assertFalse(apply_change(self.cfg, 'set_connection_hotkey', {'shortcut': 'cmd+alt+ctrl+i'}))
        self.assertEqual(self.cfg.connection_hotkey, 'ctrl+alt+cmd+i')
        self.assertEqual(Config.from_dict(self.cfg.to_dict()).connection_hotkey, self.cfg.connection_hotkey)
        for bad in (None, 34, True, 'i', 'alt+i', 'ctrl+ctrl+i', 'ctrl+cmd+unknown', 'ctrl+cmd+I', 'ctrl+cmd+i;exit'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                Config.from_dict({'connection_hotkey': bad})
        daemon_type = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'bin/padpilotd'))['PadPilotDaemon']
        daemon = daemon_type.__new__(daemon_type)
        daemon.config, daemon.engine, daemon.detector = self.cfg, self.engine, self.detector
        daemon.config_lock = threading.RLock()
        self.engine.runtime.retry_count = 3
        with patch.dict(daemon.apply_config_change.__globals__, save_config=lambda _: None):
            result = json.loads(daemon.handle_client_cmd(json.dumps({
                'command': 'set_connection_hotkey', 'params': {'shortcut': ''}, 'expected_revision': 1})))
        self.assertTrue(result['ok'])
        self.assertEqual(daemon.config.connection_hotkey, '')
        self.assertEqual(self.engine.runtime.retry_count, 3)
        self.detector.observe.assert_not_called()
        self.bd.connect_sidecar.assert_not_called()

    def test_hotkey_does_not_restart_stopped_automatic_service(self):
        action = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'bin/padpilot-cli'))['cmd_action']
        start = MagicMock()
        with patch.dict(action.__globals__, send_daemon_cmd=lambda *a, **kw: 'Daemon is not running',
                        cmd_start=start, load_config=lambda: self.cfg):
            with self.assertRaisesRegex(RuntimeError, '背景服務已停止'):
                action(argparse.Namespace(action='connect_ipad'))
        start.assert_not_called()

    def test_failure_details_survive_engine_ipc_cli_without_duplicate_notification(self):
        daemon_type = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'bin/padpilotd'))['PadPilotDaemon']
        daemon = daemon_type.__new__(daemon_type)
        daemon.engine, daemon.config = self.engine, self.cfg
        for key in ('sidecar_connection', 'sidecar_identity', 'sidecar', 'usb', 'displays', 'identifiers'):
            self.actual.discovery_errors = {key: 'Failed. "test"\\detail'}
            response = daemon.handle_client_cmd('connect_ipad')
            self.assertIn('Failed. "test"\\detail', response)
            self.assertIn('no connection was started', response)
        self.actual.discovery_errors = {'sidecar_connection': 'Failed.'}
        self.actual.sidecar_available = False
        response = daemon.handle_client_cmd('connect_ipad')
        self.assertIn('missing from the Sidecar device list', response)
        self.assertEqual(response, 'ERROR: ' + self.engine.runtime.last_error)
        self.bd.connect_sidecar.assert_not_called()
        cli = str(Path(__file__).resolve().parents[1] / 'bin/padpilot-cli')
        try:
            for language, expected in [('zh-Hant', '尚未發起連線'), ('en', 'no connection was started'), ('ja', '接続は開始していません')]:
                self.cfg.language = language
                with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()) as output, \
                     patch('core.config.APP_SUPPORT_DIR', Path(directory)), \
                     patch('core.config.load_config', return_value=self.cfg), \
                     patch('core.notifier.notify_error') as notify, patch('socket.socket') as socket, \
                     patch.object(sys, 'argv', [cli, 'action', 'connect_ipad']):
                    (Path(directory) / 'padpilot.sock').touch()
                    socket.return_value.__enter__.return_value.recv.return_value = response.encode()
                    with self.assertRaises(SystemExit) as stopped:
                        runpy.run_path(cli, run_name='__main__')
                    self.assertEqual(stopped.exception.code, 1)
                    self.assertIn(expected, output.getvalue())
                    self.assertIn('Failed.', output.getvalue())
                    self.assertIn('BetterDisplay', output.getvalue())
                    notify.assert_not_called()
        finally:
            set_language('zh-Hant')
        self.actual.discovery_errors = {}
        self.cfg.ipad = self.actual.resolved_ipad = IpadConfig()
        self.assertFalse(self.engine.request_sidecar_connection(async_transition=False))
        self.assertIn('尚未設定連線用的 iPad', tr_message(self.engine.runtime.last_error))
