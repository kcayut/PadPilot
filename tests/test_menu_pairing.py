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
MENU = runpy.run_path(str(ROOT / 'core/menu.py'))
CLI = runpy.run_path(str(ROOT / 'bin/padpilot-cli'))
DAEMON = runpy.run_path(str(ROOT / 'bin/padpilotd'))
UUID = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
DEVICE = dict(name='工作 iPad', sidecar_uuid=UUID, usb_serial='serial-1')


def rendered(status, cfg):
    return MENU['render'](status, cfg, True, now=1000)


class MenuPairingTests(unittest.TestCase):
    def test_template_icons_match_snapshot_and_transition(self):
        import struct
        for icon, name in [('📱', 'ipad'), ('🖥️', 'physical'), ('◻️', 'virtual'),
                           ('⏸️', 'paused'), ('⚠️', 'warning')]:
            status = {'icon': icon, 'actual': {'timestamp': 1000, 'sidecar_devices': []}}
            self.assertEqual(rendered(status, {})['icon'], name)
            data = (ROOT / 'assets/menu-icons' / f'{name}.png').read_bytes()
            self.assertEqual(struct.unpack('>II', data[16:24]), (36, 36))
        self.assertEqual(rendered({}, {})['icon'], 'warning')
        status = {'icon': '📱', 'actual': {'timestamp': 1000, 'sidecar_devices': []},
                  'runtime': {'transition_state': 'CONNECTING'}}
        self.assertEqual(rendered(status, {})['icon'], 'working')
        status['runtime']['last_error'] = 'failed'
        self.assertEqual(rendered(status, {})['icon'], 'warning')

    def test_hidden_menu_does_not_load_state(self):
        function = MENU['read_menu']
        load = MagicMock()
        with patch.dict(function.__globals__, {'load_status': load, 'state_file_exists': lambda _: True}):
            self.assertTrue(function()['hidden'])
        load.assert_not_called()

    def test_service_action_uses_process_state_not_snapshot_age(self):
        from core.i18n import LANGUAGES, set_language, tr
        from core.autostart import daemon_pids
        try:
            for language in LANGUAGES:
                for stamp in (0, 1000):
                    for running, label, action in (
                        (True, '服務狀態：執行中', 'stop'),
                        (False, '服務狀態：已停止', 'start'),
                        (None, '服務狀態：無法確認', None),
                    ):
                        rows = MENU['render']({'actual': {'timestamp': stamp}}, {'language': language},
                                              False, now=1000, service_running=running)['items']
                        self.assertIn(tr(label), [r['title'] for r in rows])
                        actions = [r['args'] for r in rows if r['args'] in (['start'], ['stop'])]
                        self.assertEqual(actions, [[action]] if action else [])
            read_menu = MENU['read_menu']
            for pids, expected in (([777], True), ([], False), (RuntimeError('query failed'), None)):
                probe = MagicMock(side_effect=pids) if isinstance(pids, Exception) else MagicMock(return_value=pids)
                draw = MagicMock()
                with patch('pathlib.Path.exists', return_value=False), \
                     patch.dict(read_menu.__globals__, daemon_pids=probe, load_json=lambda *a: {},
                                load_status=lambda: {}, render=draw):
                    read_menu()
                self.assertIs(draw.call_args.kwargs['service_running'], expected)
            results = [subprocess.CompletedProcess([], 0, output, '') for output in
                       ('777\n', '/usr/bin/python3\n', f'/usr/bin/python3 {ROOT}/bin/padpilotd\n')]
            with patch('core.autostart.subprocess.run', side_effect=results) as run:
                self.assertEqual(daemon_pids(), [777])
                self.assertIn('padpilotd', run.call_args_list[0].args[0][-1])
                self.assertEqual(run.call_args.kwargs['timeout'], 2)
        finally:
            set_language('zh-Hant')

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
        rows = rendered(status, cfg)['items']
        device = next(r for r in rows if 'bash=/tmp/evil' in r['title'])
        self.assertEqual(device['depth'], 1)
        self.assertEqual(device['args'], [])
        self.assertNotIn('\n', device['title'])
        resolution = next(r for r in rows if '解析度' in r['title'])
        self.assertEqual(resolution['depth'], 2)
        self.assertEqual(rows[-1]['args'], ['exit'])
        self.assertEqual(rows[-1]['title'], '結束')

    def test_offline_profiles_and_stale_data_are_not_available(self):
        cfg = {'ipad': DEVICE, 'paired_ipads': [DEVICE]}
        rows = rendered({}, cfg)['items']
        self.assertTrue(any('工作 iPad — 狀態未知' in r['title'] for r in rows))
        self.assertFalse(next(r for r in rows if r['title'] == '設為主螢幕')['enabled'])
        status = {'configured_ipad': DEVICE, 'actual': {'timestamp': 1000,
                  'sidecar_devices': [], 'discovery_errors': {'sidecar': 'timeout'}}}
        self.assertTrue(any('工作 iPad — 狀態未知' in r['title'] for r in rendered(status, cfg)['items']))
        status['actual']['discovery_errors'] = {}
        self.assertTrue(any('工作 iPad — 未偵測到' in r['title'] for r in rendered(status, cfg)['items']))
        for running in (False, None):
            rows = MENU['render'](status, cfg, False, now=1000, service_running=running)['items']
            self.assertFalse(next(r for r in rows if r['args'] == ['action', 'use_ipad_main'])['enabled'])

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
        save = MagicMock()
        with patch.dict(function.__globals__, {'load_config': Config, 'save_config': save,
             'send_daemon_cmd': lambda *a, **kw: 'Daemon response timed out'}):
            with self.assertRaises(RuntimeError):
                function(DEVICE, True)
        save.assert_not_called()

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
            'atomic_write': lambda *_: events.append('hide'),
        }), contextlib.redirect_stdout(io.StringIO()):
            function(argparse.Namespace())
        self.assertEqual(events, ['stop', 'hide'])
        refresh = MagicMock()
        with patch.dict(function.__globals__, {'cmd_stop': MagicMock(side_effect=RuntimeError('still running')),
                                               'open_menu_app': refresh}):
            with self.assertRaises(RuntimeError):
                function(argparse.Namespace())
        refresh.assert_not_called()

    def test_stop_preserves_state_when_launchd_is_still_loaded(self):
        function = CLI['cmd_stop']
        with patch.dict(function.__globals__, stop_daemon=MagicMock(side_effect=RuntimeError('still loaded'))), \
             patch('pathlib.Path.unlink') as unlink, patch('os.kill') as kill:
            with self.assertRaises(RuntimeError):
                function(argparse.Namespace())
        unlink.assert_not_called()
        kill.assert_not_called()

    def test_stop_verifies_processes_before_deleting_runtime_files(self):
        function = CLI['cmd_stop']
        stopped = MagicMock()
        unlink = MagicMock()
        with patch.dict(function.__globals__, {'stop_daemon': stopped, 'remove_state_file': unlink}), \
             contextlib.redirect_stdout(io.StringIO()):
            function(argparse.Namespace(exiting=True))
        stopped.assert_called_once_with()
        self.assertTrue(unlink.called)

    def test_missing_tk_only_disables_gui_actions(self):
        rows = MENU['render']({}, {}, False, gui_available=False, service_running=False)['items']
        gui = [row for row in rows if row['args'][:1] == ['gui']]
        self.assertTrue(gui)
        self.assertTrue(all(not row['enabled'] for row in gui))
        self.assertTrue(next(row for row in rows if row['args'] == ['start'])['enabled'])

    def test_start_opens_native_menu_unless_called_by_the_app(self):
        function = CLI['cmd_start']
        launch = MagicMock()
        with patch.dict(function.__globals__, {'daemon_pids': lambda: [777], 'open_menu_app': launch,
                                               'wait_for_daemon': MagicMock()}), \
             patch('pathlib.Path.unlink'), contextlib.redirect_stdout(io.StringIO()):
            function(argparse.Namespace(no_menu=False))
            launch.assert_called_once_with()
            launch.reset_mock()
            function(argparse.Namespace(no_menu=True))
            launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
