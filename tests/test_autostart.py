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


class TestSidecarSwitchAutostart(unittest.TestCase):
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
        self.assertEqual(data['BundleProgram'], 'Contents/MacOS/SidecarSwitch')
        self.assertEqual(data['ProgramArguments'], ['SidecarSwitch', '--daemon'])
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
        self.assertFalse(self.cfg.connect_on_boot)
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

    def test_boot_enable_is_one_transaction_and_failure_restores_both_options(self):
        for failure in (None, 'handshake', 'approval'):
            with self.subTest(failure=failure):
                self.cfg = Config(autostart_on_login=False, connect_on_boot=False, revision=7,
                                  login_service_initialized=True)
                before = self.cfg.to_dict()
                self.state = 'notRegistered'
                self.wait_for_daemon.side_effect = RuntimeError('handshake failed') if failure == 'handshake' else None
                original = self.service_command.side_effect
                if failure == 'approval':
                    def pending(action='status', app=None):
                        if action == 'register':
                            self.state = 'requiresApproval'
                            return self.state
                        return original(action, app)
                    self.service_command.side_effect = pending
                ok, _ = autostart.set_autostart(True, expected_revision=7, connect_on_boot=True)
                self.service_command.side_effect = original
                self.assertEqual(ok, failure is None)
                if ok:
                    self.assertTrue(self.cfg.autostart_on_login and self.cfg.connect_on_boot)
                    self.assertEqual(self.cfg.revision, 8)
                else:
                    self.assertEqual(self.cfg.to_dict(), before)
                    self.assertEqual(self.state, 'notRegistered')

    def test_cli_boot_enable_uses_service_transaction_and_validates_input(self):
        submit = runpy.run_path(str(ROOT / 'bin/sidecarswitch-cli'))['submit_settings']
        service = MagicMock(return_value=(True, 'OK'))
        ipc = MagicMock()
        with patch.dict(submit.__globals__, set_autostart=service, send_daemon_cmd=ipc), contextlib.redirect_stdout(io.StringIO()):
            submit('set_connect_on_boot', {'enabled': True}, 7)
            service.assert_called_once_with(True, 7, connect_on_boot=True)
            ipc.assert_not_called()
            for payload in ({'enabled': 1}, {'enabled': 'true'}, {'enabled': True, 'extra': 1}, None):
                with self.assertRaises(ValueError):
                    submit('set_connect_on_boot', payload, 7)

    def test_direct_settings_cannot_bypass_login_service_and_menu_warns(self):
        from core.settings import apply_change
        from core.menu import render
        cfg = Config(autostart_on_login=False, connect_on_boot=False)
        with self.assertRaises(ValueError):
            apply_change(cfg, 'set_connect_on_boot', {'enabled': True})
        with self.assertRaises(ValueError):
            apply_change(cfg, 'set_autostart', {'enabled': True})
        self.assertFalse(cfg.autostart_on_login or cfg.connect_on_boot)
        cfg.autostart_on_login = cfg.connect_on_boot = True
        row = next(row for row in render({}, cfg.to_dict(), True)['items'] if row['args'][:1] == ['autostart'])
        self.assertEqual(len(row['confirmation']), 4)
        self.assertEqual(row['args'][-2:], ['--expected-revision', str(cfg.revision)])
        for state in ('enabled', 'requiresApproval', 'notRegistered', 'notFound', 'unknown'):
            for boot in (False, True):
                cfg.connect_on_boot = boot
                row = next(row for row in render({}, cfg.to_dict(), state == 'enabled', login_service_status=state)['items']
                           if row['args'][:1] == ['autostart'])
                self.assertEqual('confirmation' in row, boot and state in ('enabled', 'requiresApproval'))
        apply_change(cfg, 'set_connect_on_boot', {'enabled': False})
        self.assertTrue(cfg.autostart_on_login)
        self.assertFalse(cfg.connect_on_boot)

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
        command = runpy.run_path(str(ROOT / 'bin/sidecarswitch-cli'))['cmd_start']
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
            first, second = root / 'first/SidecarSwitch.app', root / 'second/SidecarSwitch.app'
            for app in (first, second):
                plist = app / 'Contents/Library/LaunchAgents/com.sidecarswitch.daemon.plist'
                plist.parent.mkdir(parents=True)
                plist.write_text(autostart.generate_plist_content())
            state = {'value': 'notFound'}
            calls = []
            def run(command, **kwargs):
                if command[0] == 'launchctl':
                    return __import__('subprocess').CompletedProcess(command, 0,
                        'managed_by = com.apple.xpc.ServiceManagement\nparent bundle identifier = com.sidecarswitch.app\n'
                        'program identifier = Contents/MacOS/SidecarSwitch (mode: 2)\n', '')
                calls.append(command[-1])
                if command[-1] == 'register': state['value'] = 'enabled'
                return __import__('subprocess').CompletedProcess(command, 0, state['value'], '')
            with patch.object(autostart, 'APP_SUPPORT_DIR', root / 'support'), \
                 patch.object(autostart.subprocess, 'run', side_effect=run):
                self.assertEqual(ORIGINAL_COMMAND('register', first), 'enabled')
                self.assertEqual(autostart.service_owner(), first)
                self.assertEqual(ORIGINAL_COMMAND('status', first), 'enabled')
                self.assertTrue(autostart.job_loaded(first / 'Contents/Library/LaunchAgents/com.sidecarswitch.daemon.plist'))
                with self.assertRaisesRegex(RuntimeError, 'another installation'):
                    autostart.job_loaded(second / 'Contents/Library/LaunchAgents/com.sidecarswitch.daemon.plist')
                for action in ('status', 'register', 'unregister'):
                    with self.assertRaisesRegex(RuntimeError, 'another installation'):
                        ORIGINAL_COMMAND(action, second)
                self.assertNotIn('unregister', calls)
                self.assertEqual(calls.count('register'), 1)
                self.assertFalse((root / 'Library/LaunchAgents').exists())
                with self.assertRaisesRegex(RuntimeError, 'removal was not confirmed'):
                    ORIGINAL_COMMAND('unregister', first)
                moved = root / 'Applications/SidecarSwitch.app'
                moved.parent.mkdir()
                first.rename(moved)
                self.assertEqual(ORIGINAL_COMMAND('status', moved), 'enabled')
                self.assertTrue(autostart.job_loaded(moved / 'Contents/Library/LaunchAgents/com.sidecarswitch.daemon.plist'))
                self.assertEqual(autostart.service_owner(), first)  # Status queries remain read-only.
                self.assertEqual(ORIGINAL_COMMAND('register', moved), 'enabled')
                self.assertEqual(autostart.service_owner(), moved)
                with self.assertRaisesRegex(RuntimeError, 'another installation'):
                    ORIGINAL_COMMAND('status', second)

    def test_system_app_is_discovered_only_for_the_matching_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            app = root / 'Applications/SidecarSwitch.app'
            resources = app / 'Contents/Resources'
            resources.mkdir(parents=True)
            metadata = resources / 'runtime.json'
            metadata.write_text(json.dumps({'project_root': str(root), 'python': '/usr/bin/python3'}))
            (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.sidecarswitch.app'}))
            with patch.object(autostart, 'PROJECT_ROOT', root), \
                 patch.object(autostart, 'APP_SUPPORT_DIR', root / 'support'), \
                 patch('core.runtime.SYSTEM_APP', app), patch.object(Path, 'home', return_value=root / 'home'):
                self.assertEqual(autostart.find_menu_app(), app)
                metadata.write_text(json.dumps({'project_root': '/another/project', 'python': '/usr/bin/python3'}))
                self.assertIsNone(autostart.find_menu_app())

    def test_menu_launcher_only_opens_matching_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            app = root / 'build/SidecarSwitch.app/Contents/Resources'
            app.mkdir(parents=True)
            (app / 'runtime.json').write_text(json.dumps({'project_root': str(root), 'python': '/usr/bin/python3'}))
            (app.parent / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.sidecarswitch.app'}))
            with patch.object(autostart, 'PROJECT_ROOT', root), patch.object(Path, 'home', return_value=root), \
                 patch.object(autostart.subprocess, 'run', return_value=MagicMock(returncode=0)) as run:
                self.assertTrue(autostart.open_menu_app())
                self.assertEqual(run.call_args.args[0], ['open', '-g', '-a', str(root / 'build/SidecarSwitch.app'),
                                                       'sidecarswitch://menu', '--args', '--menu-only'])
                (app / 'runtime.json').write_text(json.dumps({'project_root': '/different/checkout'}))
                run.reset_mock()
                self.assertFalse(autostart.open_menu_app())
                run.assert_not_called()


ORIGINAL_COMMAND = autostart.service_command
ORIGINAL_STOP = autostart.stop_daemon
if __name__ == '__main__':
    unittest.main()
