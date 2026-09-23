"""Native launch and guarded controls never touch displays in these checks."""
import argparse
import json
import plistlib
import runpy
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core import autostart, gui
from core.config import Config
from core.models import IpadConfig, pairing_key

ROOT = Path(__file__).resolve().parents[1]
CLI = runpy.run_path(str(ROOT / 'bin/sidecarswitch-cli'))
DAEMON = runpy.run_path(str(ROOT / 'bin/sidecarswitchd'))


class NativeBridgeTests(unittest.TestCase):
    def test_decision_refresh_never_starts_service_and_respects_readonly(self):
        function = CLI['cmd_gui_data']
        import io
        from contextlib import redirect_stdout
        for readonly in (False, True):
            send = MagicMock(return_value='Daemon is not running. (Socket not found)')
            with patch.dict(function.__globals__, send_daemon_cmd=send), \
                 patch.object(gui, 'read_view', return_value={'config_error': 'invalid' if readonly else ''}), \
                 patch.object(gui, 'build_gui_payload', return_value={'status': 'saved'}), redirect_stdout(io.StringIO()):
                function(argparse.Namespace(refresh=True, scan=False, diagnostics=False, admin_checks=False, logs=False))
            self.assertEqual(send.call_count, 0 if readonly else 1)
            if not readonly:
                self.assertEqual(send.call_args.args[0], 'refresh')

    def test_gui_opens_owned_app_with_reusable_url_and_no_new_instance(self):
        with patch.object(autostart, 'find_menu_app', return_value=Path('/tmp/SidecarSwitch.app')), \
             patch.object(gui.subprocess, 'run') as run:
            gui.run_gui('diagnostics')
            command = run.call_args.args[0]
            self.assertEqual(command, ['/usr/bin/open', '-a', '/tmp/SidecarSwitch.app',
                                       'sidecarswitch://settings?page=diagnostics', '--args', '--settings'])
            gui.run_gui('wizard', select='a' * 64)
            self.assertIn('page=search&select=' + 'a' * 64, run.call_args.args[0][3])
            for invalid in ('../file', 'x' * 64):
                with self.assertRaises(ValueError):
                    gui.run_gui(delete=invalid)
            with self.assertRaises(ValueError):
                gui.run_gui(delete='a' * 64, select='b' * 64)
            self.assertEqual(run.call_count, 2)

    def test_stale_guarded_action_does_not_start_a_stopped_service(self):
        command = CLI['cmd_action']
        start = MagicMock()
        with patch.dict(command.__globals__, send_daemon_cmd=MagicMock(return_value='Daemon is not running'),
                        load_config=MagicMock(return_value=Config(revision=4)), cmd_start=start):
            with self.assertRaises(RuntimeError):
                command(argparse.Namespace(action='use_ipad_main', expected_revision=3, target_key='a' * 64))
        start.assert_not_called()

    def test_explicit_valid_control_starts_service_then_rechecks_guard_in_daemon(self):
        import io
        from contextlib import redirect_stdout
        cfg = Config(revision=3, ipad=IpadConfig('Test', 'uuid', 'serial'))
        command, start = CLI['cmd_action'], MagicMock()
        send = MagicMock(side_effect=['Daemon is not running', '{"ok": true, "message": "OK"}'])
        with patch.dict(command.__globals__, send_daemon_cmd=send, load_config=lambda: cfg, cmd_start=start), \
             patch('time.sleep'), redirect_stdout(io.StringIO()):
            command(argparse.Namespace(action='use_ipad_main', expected_revision=3,
                                       target_key=pairing_key(cfg.ipad.to_dict())))
        self.assertTrue(start.call_args.args[0].no_menu)
        self.assertEqual(send.call_args_list[0].args, send.call_args_list[1].args)
        self.assertEqual(json.loads(send.call_args.args[0])['expected_revision'], 3)

    def test_settings_launcher_skips_foreign_or_legacy_installed_app_for_native_build(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            source = home / 'source'
            installed = home / 'Applications/SidecarSwitch.app'
            built = source / 'build/SidecarSwitch.app'
            modern = {'CFBundleIdentifier': 'com.sidecarswitch.app', 'CFBundleURLTypes': [{'CFBundleURLSchemes': ['sidecarswitch']}]}
            for app in (installed, built):
                (app / 'Contents/Resources').mkdir(parents=True)
                (app / 'Contents/Resources/runtime.json').write_text(json.dumps({'project_root': str(source), 'python': '/usr/bin/python3'}))
                (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(modern))
            with patch('pathlib.Path.home', return_value=home), patch.object(autostart, 'PROJECT_ROOT', source):
                for runtime_root, info in ((home / 'other-source', modern), (source, {'CFBundleIdentifier': 'com.sidecarswitch.app'})):
                    with self.subTest(runtime=str(runtime_root), native=bool(info)):
                        (installed / 'Contents/Resources/runtime.json').write_text(json.dumps({'project_root': str(runtime_root), 'python': '/usr/bin/python3'}))
                        (installed / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
                        self.assertEqual(autostart.find_menu_app(settings=True), built)
                self.assertEqual(autostart.find_menu_app(), installed)
                (built / 'Contents/Info.plist').write_bytes(plistlib.dumps({}))
                self.assertIsNone(autostart.find_menu_app(settings=True))

    def test_guarded_action_checks_revision_and_exact_target_inside_daemon(self):
        cls = DAEMON['SidecarSwitchDaemon']
        obj = cls.__new__(cls)
        obj.config = Config(revision=3, ipad=IpadConfig('Test', 'uuid', 'serial'))
        obj.engine = MagicMock()
        obj.engine.run_control.side_effect = lambda action: action()
        key = pairing_key(obj.config.ipad.to_dict())
        for revision, target, error in ((2, key, 'CONFIG_CONFLICT'), (3, 'a' * 64, 'TARGET_CHANGED'),
                                        (True, key, 'CONFIG_CONFLICT'), (None, key, 'CONFIG_CONFLICT')):
            response = obj.handle_client_cmd(json.dumps({'command': 'use_ipad_main',
                'expected_revision': revision, 'params': {'target_key': target}}))
            self.assertEqual(json.loads(response)['error'], error)
        obj.engine.set_user_override.assert_not_called()
        response = obj.handle_client_cmd(json.dumps({'command': 'use_ipad_main',
            'expected_revision': 3, 'params': {'target_key': key}}))
        self.assertTrue(json.loads(response)['ok'])
        obj.engine.set_user_override.assert_called_once()


    def test_unsafe_config_resolution_still_returns_readonly_window(self):
        with patch.object(gui, 'get_config_file_path', side_effect=gui.UnsafePathError('unsafe')), \
             patch.object(gui, 'read_status', return_value={}), patch.object(gui, 'BetterDisplayCLI') as hardware:
            hardware.resolve_cli_path.return_value = None
            payload = gui.build_gui_payload(scan=True)
            self.assertTrue(payload['ui']['readonly'])
            self.assertEqual(payload['paths']['config'], '')
            hardware.assert_not_called()



if __name__ == '__main__':
    unittest.main()
