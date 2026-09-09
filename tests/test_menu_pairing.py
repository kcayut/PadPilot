"""Menu, pairing and exit regressions; all hardware/process actions are mocked."""
import argparse
import contextlib
import io
import runpy
import subprocess
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.betterdisplay import BetterDisplayCLI
from core.config import Config
from core.detector import DisplayDetector
from core.models import DisplayInfo

ROOT = Path(__file__).resolve().parents[1]
MENU = runpy.run_path(str(ROOT / 'swiftbar/padpilot.30s.py'))
CLI = runpy.run_path(str(ROOT / 'bin/padpilot-cli'))
DAEMON = runpy.run_path(str(ROOT / 'bin/padpilotd'))
UUID = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
DEVICE = dict(name='工作 iPad', sidecar_uuid=UUID, usb_serial='serial-1')


def rendered(status, cfg):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        MENU['render'](status, cfg, True, now=1000)
    return out.getvalue()


class MenuPairingTests(unittest.TestCase):
    def test_hidden_menu_outputs_nothing_without_loading_state(self):
        function = MENU['main']
        load = MagicMock()
        output = io.StringIO()
        with patch('pathlib.Path.exists', return_value=True), \
             patch.dict(function.__globals__, {'load_status': load}), \
             contextlib.redirect_stdout(output):
            function()
        self.assertEqual(output.getvalue(), '')
        load.assert_not_called()

    def test_other_ipad_does_not_satisfy_current_target(self):
        cfg = Config.from_dict({'ipad': DEVICE})
        bd = MagicMock(spec=BetterDisplayCLI)
        bd.check_virtual_display.return_value = (False, False)
        bd.get_sidecar_list.return_value = [{'name': 'Other iPad', 'uuid': OTHER}]
        detector = DisplayDetector(cfg, bd)
        with patch.object(detector, 'get_online_displays', return_value=[
            DisplayInfo(2, 'Other iPad', is_sidecar=True)]), \
             patch.object(detector, 'parse_usb_devices', return_value=[]):
            actual, _ = detector.observe()
        self.assertFalse(actual.sidecar_connected)
        self.assertFalse(actual.sidecar_available)
        self.assertEqual(len(actual.online_displays), 1)

    def test_old_config_migrates_and_identity_upsert_preserves_other_settings(self):
        cfg = Config.from_dict({'ipad': DEVICE, 'cooldown_seconds': 77})
        self.assertEqual(len(cfg.paired_ipads), 1)
        cfg.remember_ipad(dict(DEVICE, sidecar_uuid=UUID.lower()), True)
        cfg.remember_ipad(dict(name='工作 iPad', sidecar_uuid=OTHER, usb_serial='serial-2'))
        loaded = Config.from_dict(cfg.to_dict())
        self.assertEqual(len(loaded.paired_ipads), 2)
        self.assertEqual(loaded.ipad.sidecar_uuid, UUID)
        self.assertEqual(loaded.cooldown_seconds, 77)
        with self.assertRaises(ValueError):
            loaded.remember_ipad(dict(DEVICE, sidecar_uuid=OTHER))
        with self.assertRaises(ValueError):
            loaded.remember_ipad(dict(DEVICE, name='bad\nname'))
        with self.assertRaises(ValueError):
            loaded.remember_ipad(dict(DEVICE, sidecar_uuid='invalid'))

    def test_menu_hierarchy_exit_and_untrusted_names(self):
        evil = '屏幕\n--Exit | bash=/tmp/evil'
        cfg = {'ipad': DEVICE, 'paired_ipads': [DEVICE]}
        status = {'configured_ipad': DEVICE, 'mode': 'automatic', 'actual': {
            'timestamp': 1000, 'sidecar_devices': [], 'online_displays': [
                {'name': evil, 'width': 1280, 'height': 720}],
            'discovery_errors': {}, 'sidecar_connected': False}}
        text = rendered(status, cfg)
        self.assertIn('\n螢幕與裝置 |', text)
        self.assertIn('\n--🖥️', text)
        self.assertIn('\n----解析度', text)
        self.assertNotIn('\n--Exit | bash=/tmp/evil', text)
        self.assertNotIn(' | bash=/tmp/evil', text)
        self.assertIn('配對精靈 Wizard…', text)
        exit_line = text.splitlines()[-1]
        self.assertTrue(exit_line.startswith('Exit PadPilot |'))
        self.assertIn('param1=exit', exit_line)
        self.assertIn('refresh=true', exit_line)
        self.assertNotIn('quit', text.lower())

    def test_offline_profiles_and_stale_data_are_not_available(self):
        cfg = {'ipad': DEVICE, 'paired_ipads': [DEVICE]}
        text = rendered({}, cfg)
        self.assertIn('工作 iPad — 狀態未知', text)
        line = next(l for l in text.splitlines() if l.startswith('--設為主螢幕'))
        self.assertNotIn('bash=', line)
        self.assertIn('Exit PadPilot', text)
        status = {'configured_ipad': DEVICE, 'actual': {'timestamp': 1000,
                  'sidecar_devices': [], 'discovery_errors': {'sidecar': 'timeout'}}}
        self.assertIn('工作 iPad — 狀態未知', rendered(status, cfg))
        status['actual']['discovery_errors'] = {}
        self.assertIn('工作 iPad — 未偵測到', rendered(status, cfg))

    def test_discovery_failure_and_empty_are_distinct_and_names_are_clean(self):
        bd = BetterDisplayCLI.__new__(BetterDisplayCLI)
        with patch.object(bd, 'is_available', return_value=True), patch.object(bd, 'run_cmd') as run:
            run.return_value = (0, '', '')
            self.assertEqual(bd.get_sidecar_list(), [])
            self.assertEqual(bd.sidecar_error, '')
            run.return_value = (-1, '', 'timeout')
            self.assertEqual(bd.get_sidecar_list(), [])
            self.assertEqual(bd.sidecar_error, 'timeout')
            for raw in (f"工作 iPad, {UUID}", f"工作 iPad (UUID: {UUID})"):
                run.return_value = (0, raw, '')
                self.assertEqual(bd.get_sidecar_list()[0]['name'], '工作 iPad')

    def test_wizard_cancel_and_save_without_activating(self):
        function = CLI['cmd_pair']
        bd, detector, save = MagicMock(), MagicMock(), MagicMock()
        bd.get_sidecar_list.return_value = [{'name': DEVICE['name'], 'uuid': UUID}]
        bd.sidecar_error = detector.usb_error = ''
        detector.parse_usb_devices.return_value = []
        args = argparse.Namespace(interactive=True, device=None)
        replacements = {'load_config': Config, 'BetterDisplayCLI': lambda _: bd,
                        'DisplayDetector': lambda *_: detector, 'save_pairing': save}
        with patch.dict(function.__globals__, replacements), contextlib.redirect_stdout(io.StringIO()):
            with patch('builtins.input', side_effect=['1', '', 'n', 'n']):
                function(args)
            save.assert_not_called()
            with patch('builtins.input', side_effect=['1', '', 'n', 'y']):
                function(args)
            self.assertFalse(save.call_args.args[1])
            with patch('builtins.input', return_value='q'), self.assertRaises(KeyboardInterrupt):
                function(args)

    def test_pairing_timeout_does_not_fallback_to_unlocked_write(self):
        function = CLI['save_pairing']
        save, refresh = MagicMock(), MagicMock()
        with patch.dict(function.__globals__, {'load_config': Config, 'save_config': save,
             'refresh_menu': refresh, 'send_daemon_cmd': lambda *a, **kw: 'Daemon response timed out'}):
            with self.assertRaises(RuntimeError):
                function(DEVICE, True)
        save.assert_not_called()
        refresh.assert_not_called()

    def test_daemon_profile_save_does_not_trigger_display_transition(self):
        cls = DAEMON['PadPilotDaemon']
        obj = cls.__new__(cls)
        obj.detector, obj.engine = MagicMock(), MagicMock()
        import json
        with patch.dict(cls.handle_client_cmd.__globals__, {'load_config': Config, 'save_config': MagicMock()}):
            response = obj.handle_client_cmd('save_pairing:' + json.dumps({'ipad': DEVICE, 'activate': False}))
            self.assertTrue(response.startswith('OK:'))
            obj.engine.reset_automation.assert_not_called()
            obj.engine.evaluate.assert_not_called()
            response = obj.handle_client_cmd('save_pairing:' + json.dumps({'ipad': DEVICE, 'activate': True}))
            self.assertTrue(response.startswith('OK:'))
            obj.engine.reset_automation.assert_called_once()

    def test_exit_only_hides_after_successful_stop(self):
        function = CLI['cmd_exit']
        events = []
        with patch.dict(function.__globals__, {
            'cmd_stop': lambda _: events.append('stop'),
            'MENU_HIDDEN': MagicMock(touch=lambda: events.append('hide')),
            'refresh_menu': lambda: events.append('refresh'),
        }), contextlib.redirect_stdout(io.StringIO()):
            function(argparse.Namespace())
        self.assertEqual(events, ['stop', 'hide', 'refresh'])
        refresh = MagicMock()
        with patch.dict(function.__globals__, {'cmd_stop': MagicMock(side_effect=RuntimeError('still running')),
                                               'refresh_menu': refresh}):
            with self.assertRaises(RuntimeError):
                function(argparse.Namespace())
        refresh.assert_not_called()

    def test_stop_preserves_state_when_launchd_is_still_loaded(self):
        function = CLI['cmd_stop']
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0)), \
             patch('pathlib.Path.unlink') as unlink, patch('os.kill') as kill:
            with self.assertRaises(RuntimeError):
                function(argparse.Namespace())
        unlink.assert_not_called()
        kill.assert_not_called()

    def test_stop_verifies_processes_before_deleting_runtime_files(self):
        function = CLI['cmd_stop']
        pids = MagicMock(side_effect=[[777], [], []])
        refresh = MagicMock()
        with patch.dict(function.__globals__, {'daemon_pids': pids, 'refresh_menu': refresh}), \
             patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1)), \
             patch('pathlib.Path.unlink') as unlink, patch('os.kill') as kill, \
             contextlib.redirect_stdout(io.StringIO()):
            function(argparse.Namespace(exiting=True))
        kill.assert_called_once()
        self.assertTrue(unlink.called)
        refresh.assert_not_called()


if __name__ == '__main__':
    unittest.main()
