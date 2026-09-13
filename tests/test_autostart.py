"""Login service lifecycle checks; no real registrations or display operations."""
import argparse
import contextlib
import copy
import io
import json
import plistlib
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core import autostart
from core.config import Config

ROOT = Path(__file__).resolve().parents[1]


class TestPadPilotAutostart(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.state = 'notRegistered'
        self.actions = []
        self.running = False
        def service(action='status', app=None):
            self.actions.append(action)
            if action == 'register': self.state = 'enabled'
            elif action == 'unregister': self.state = 'notRegistered'
            return self.state
        for name, options in (
            ('load_config', {'side_effect': lambda: copy.deepcopy(self.cfg)}),
            ('save_config', {'side_effect': lambda cfg: setattr(self, 'cfg', copy.deepcopy(cfg))}),
            ('service_command', {'side_effect': service}),
            ('is_daemon_running', {'side_effect': lambda: self.running}),
            ('stop_daemon', {}), ('wait_for_daemon', {}), ('start_registered', {}), ('start_standalone', {}),
        ):
            mocker = patch.object(autostart, name, **options)
            setattr(self, name, mocker.start())
            self.addCleanup(mocker.stop)

    def test_relative_agent_has_no_external_paths_and_normal_exit_does_not_restart(self):
        data = plistlib.loads(autostart.generate_plist_content().encode())
        self.assertEqual(data['BundleProgram'], 'Contents/MacOS/PadPilot')
        self.assertEqual(data['ProgramArguments'], ['PadPilot', '--daemon'])
        self.assertEqual(data['KeepAlive'], {'SuccessfulExit': False})
        self.assertTrue(data['RunAtLoad'])
        self.assertNotIn(str(Path.home()), json.dumps(data))
        self.assertNotIn('StandardErrorPath', data)

    def test_enable_disable_and_pending_toggle_preserve_current_session(self):
        self.assertTrue(autostart.enable_autostart()[0])
        self.assertTrue(self.cfg.login_service_initialized)
        self.assertTrue(autostart.is_autostart_enabled())
        self.wait_for_daemon.assert_called_once()
        self.running = True
        self.assertTrue(autostart.disable_autostart()[0])
        self.assertFalse(self.cfg.autostart_on_login)
        self.assertEqual(self.state, 'notRegistered')
        self.start_standalone.assert_called_once()
        self.state = 'requiresApproval'
        self.assertTrue(autostart.toggle_autostart()[0])
        self.assertEqual(self.state, 'notRegistered')

    def test_approval_pending_is_not_reported_enabled(self):
        self.service_command.side_effect = None
        self.service_command.return_value = 'requiresApproval'
        ok, message = autostart.enable_autostart()
        self.assertTrue(ok)
        self.assertIn('System Settings', message)
        self.assertFalse(autostart.is_autostart_enabled())
        self.start_registered.assert_not_called()
        self.start_standalone.assert_called_once()

    def test_revision_conflicts_never_overwrite_concurrent_settings(self):
        for late in (False, True):
            with self.subTest(late=late):
                self.state, self.running = 'enabled', True
                self.load_config.side_effect = [Config(revision=3 if late else 4), Config(revision=4, language='ja')]
                self.stop_daemon.reset_mock(); self.save_config.reset_mock()
                ok, message = autostart.disable_autostart(expected_revision=3)
                self.assertFalse(ok)
                self.assertIn('CONFIG_CONFLICT', message)
                self.save_config.assert_not_called()
                self.assertEqual(self.stop_daemon.call_count, int(late))
                self.assertEqual(self.state, 'enabled')
                self.assertNotIn('unregister', self.actions)

    def test_failed_registration_or_handshake_restores_preferences_and_service(self):
        self.cfg = Config(autostart_on_login=False, revision=7, login_service_initialized=True)
        before = self.cfg.to_dict()
        self.wait_for_daemon.side_effect = RuntimeError('handshake failed')
        ok, message = autostart.enable_autostart()
        self.assertFalse(ok)
        self.assertIn('restored', message)
        self.assertEqual(self.cfg.to_dict(), before)
        self.assertEqual(self.state, 'notRegistered')
        self.start_standalone.assert_not_called()

    def test_disk_failure_keeps_registration_and_restores_running_service(self):
        self.state, self.running = 'enabled', True
        self.save_config.side_effect = OSError('disk full')
        self.assertFalse(autostart.disable_autostart()[0])
        self.assertEqual(self.state, 'enabled')
        self.start_registered.assert_called_once()
        self.assertNotIn('unregister', self.actions)
        self.start_standalone.assert_not_called()

    def test_start_only_registers_once_and_respects_system_disable(self):
        command = runpy.run_path(str(ROOT / 'bin/padpilot-cli'))['cmd_start']
        for state in ('notRegistered', 'requiresApproval', 'enabled', 'unknown'):
            for initialized in (False, True):
                with self.subTest(state=state, initialized=initialized):
                    register, standalone, registered = MagicMock(return_value=(True, 'OK')), MagicMock(), MagicMock()
                    with patch.dict(command.__globals__, daemon_pids=lambda: [], remove_state_file=lambda _: None,
                                    load_config=lambda: Config(login_service_initialized=initialized),
                                    autostart_status=lambda: state, enable_autostart=register,
                                    start_standalone=standalone, start_registered=registered), contextlib.redirect_stdout(io.StringIO()):
                        command(argparse.Namespace(no_menu=True))
                    self.assertEqual(register.call_count, int(not initialized))
                    self.assertEqual(standalone.call_count, int(initialized and state != 'enabled'))
                    self.assertEqual(registered.call_count, int(initialized and state == 'enabled'))

    def test_normal_stop_never_unregisters(self):
        # Undo only the stop boundary so this exercises the real PID shutdown path.
        with patch.object(autostart, 'job_loaded', return_value=True), \
             patch.object(autostart, 'daemon_pids', side_effect=[[123], []]), \
             patch.object(autostart.os, 'kill') as kill:
            self.stop_daemon._mock_wraps = ORIGINAL_STOP
            self.stop_daemon()
            kill.assert_called_once()
            self.assertNotIn('unregister', self.actions)

    def test_registered_service_rejects_a_second_app_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            first, second = root / 'first/PadPilot.app', root / 'second/PadPilot.app'
            for app in (first, second):
                plist = app / 'Contents/Library/LaunchAgents/com.padpilot.daemon.plist'
                plist.parent.mkdir(parents=True)
                plist.write_text(autostart.generate_plist_content())
            state = {'value': 'notFound'}
            calls = []
            def run(command, **kwargs):
                calls.append(command[-1])
                if command[-1] == 'register': state['value'] = 'enabled'
                return __import__('subprocess').CompletedProcess(command, 0, state['value'], '')
            with patch.object(autostart, 'APP_SUPPORT_DIR', root / 'support'), \
                 patch.object(autostart.subprocess, 'run', side_effect=run):
                self.assertEqual(ORIGINAL_COMMAND('register', first), 'enabled')
                self.assertEqual(autostart.service_owner(), first)
                self.assertEqual(ORIGINAL_COMMAND('status', first), 'enabled')
                for action in ('status', 'register', 'unregister'):
                    with self.assertRaisesRegex(RuntimeError, 'another installation'):
                        ORIGINAL_COMMAND(action, second)
                self.assertNotIn('unregister', calls)
                self.assertEqual(calls.count('register'), 1)
                self.assertFalse((root / 'Library/LaunchAgents').exists())
                with self.assertRaisesRegex(RuntimeError, 'removal was not confirmed'):
                    ORIGINAL_COMMAND('unregister', first)

    def test_menu_launcher_only_opens_matching_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            app = root / 'build/PadPilot.app/Contents/Resources'
            app.mkdir(parents=True)
            (app / 'runtime.json').write_text(json.dumps({'project_root': str(root)}))
            with patch.object(autostart, 'PROJECT_ROOT', root), patch.object(Path, 'home', return_value=root), \
                 patch.object(autostart.subprocess, 'run', return_value=MagicMock(returncode=0)) as run:
                self.assertTrue(autostart.open_menu_app())
                self.assertEqual(run.call_args.args[0], ['open', '-g', '-a', str(root / 'build/PadPilot.app'),
                                                       'padpilot://menu', '--args', '--menu-only'])
                (app / 'runtime.json').write_text(json.dumps({'project_root': '/different/checkout'}))
                run.reset_mock()
                self.assertFalse(autostart.open_menu_app())
                run.assert_not_called()


ORIGINAL_COMMAND = autostart.service_command
ORIGINAL_STOP = autostart.stop_daemon
if __name__ == '__main__':
    unittest.main()
