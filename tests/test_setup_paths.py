"""Installer path selection and independent data removal, with no live services."""
import contextlib
import fcntl
import io
import json
import os
import re
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import check_install
import manage_app
from core.betterdisplay import BetterDisplayCLI
from core.config import Config


class SetupPathsTests(unittest.TestCase):
    def setUp(self):
        # Never discover or remove the developer's installed system App.
        system = patch('core.runtime.SYSTEM_APP', Path('/nonexistent-padpilot-test/PadPilot.app'))
        system.start()
        self.addCleanup(system.stop)

    def test_open_settings_or_failed_process_query_blocks_changes(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('pathlib.Path.home', return_value=Path(directory)), \
             patch.object(manage_app, 'FALLBACK_CONFIG_FILE', Path(directory) / 'fallback/config.json'):
            for code in (0, 2):
                with patch.object(manage_app.subprocess, 'run', return_value=subprocess.CompletedProcess([], code)):
                    with self.assertRaises(RuntimeError):
                        manage_app.ensure_settings_closed()
            with patch.object(manage_app.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)):
                manage_app.ensure_settings_closed()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_native_settings_lock_blocks_only_while_window_is_open_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            fallback = home / 'fallback/config.json'
            with patch('pathlib.Path.home', return_value=home), \
                 patch.object(manage_app, 'FALLBACK_CONFIG_FILE', fallback), \
                 patch.object(manage_app.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)):
                for support in (home / 'Library/Application Support/PadPilot', fallback.parent):
                    path = support / 'runtime/settings-window.lock'
                    path.parent.mkdir(parents=True)
                    path.write_text('unchanged')
                    path.chmod(0o644)
                    with path.open() as window:
                        fcntl.flock(window, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        with self.assertRaisesRegex(RuntimeError, 'Close PadPilot settings windows'):
                            manage_app.ensure_settings_closed()
                    manage_app.ensure_settings_closed()
                    self.assertEqual(path.read_text(), 'unchanged')
                    self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_inflight_cli_writes_block_install_only_for_this_checkout(self):
        source = Path('/tmp/source with spaces')
        with patch.object(manage_app, 'ROOT', source), \
             patch.object(manage_app.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as query:
            with self.assertRaisesRegex(RuntimeError, 'Wait for PadPilot operations to finish'):
                manage_app.ensure_settings_closed()
        pattern = query.call_args.args[0][2]
        for command in ('gui', 'open-log', 'change-settings', 'set-mode', 'set-language',
                        'autostart', 'action', 'pair', 'set-ipad', 'select-ipad'):
            self.assertRegex(f'python3 {source}/bin/padpilot-cli {command} --option', pattern)
            self.assertNotRegex(f'python3 {source}-other/bin/padpilot-cli {command} --option', pattern)
        for command in ('gui-data', 'menu-json', 'status', 'set-mode-extra'):
            self.assertNotRegex(f'python3 {source}/bin/padpilot-cli {command}', pattern)

    def test_native_settings_lock_rejects_links_and_nonregular_or_foreign_files(self):
        for kind in ('symlink', 'hardlink', 'directory', 'fifo', 'foreign', 'linked-parent'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                runtime = home / 'Library/Application Support/PadPilot/runtime'
                runtime.mkdir(parents=True)
                path = runtime / 'settings-window.lock'
                outside = home / 'outside'
                outside.write_text('keep')
                if kind == 'symlink':
                    path.symlink_to(outside)
                elif kind == 'hardlink':
                    os.link(outside, path)
                elif kind == 'directory':
                    path.mkdir()
                elif kind == 'fifo':
                    os.mkfifo(path)
                elif kind == 'linked-parent':
                    runtime.rmdir()
                    runtime.symlink_to(home, target_is_directory=True)
                else:
                    path.write_text('keep')
                with patch('pathlib.Path.home', return_value=home), \
                     patch.object(manage_app, 'FALLBACK_CONFIG_FILE', home / 'fallback/config.json'), \
                     patch.object(manage_app.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)):
                    if kind == 'foreign':
                        original = os.fstat
                        def foreign(fd):
                            values = list(original(fd))
                            values[4] = os.getuid() + 1
                            return os.stat_result(values)
                        with patch.object(manage_app.os, 'fstat', side_effect=foreign):
                            with self.assertRaisesRegex(RuntimeError, 'unsafe settings window lock'):
                                manage_app.ensure_settings_closed()
                    else:
                        with self.assertRaises(RuntimeError):
                            manage_app.ensure_settings_closed()
                self.assertEqual(outside.read_text(), 'keep')

    def test_custom_app_preflight_and_daemon_start_share_selected_path(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            app = home / 'My Apps/BetterDisplay.app'
            cli = app / 'Contents/MacOS/BetterDisplay'
            cli.parent.mkdir(parents=True)
            cli.write_text('#!/bin/sh\necho help\n')
            cli.chmod(0o755)
            cfg = home / 'Library/Application Support/PadPilot/config.json'
            cfg.parent.mkdir(parents=True)
            cfg.write_text(json.dumps({'betterdisplaycli_path': str(cli)}))
            before = cfg.read_bytes()
            with patch('pathlib.Path.home', return_value=home), \
                 patch.object(check_install.platform, 'mac_ver', return_value=('14.0', (), 'arm64')), \
                 patch.object(check_install.sys, 'platform', 'darwin'), \
                 patch.object(check_install.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'help', '')), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(check_install.resolve_betterdisplay_path(), str(cli))
                self.assertTrue(check_install.check(str(app)))
            self.assertEqual(cfg.read_bytes(), before)
            self.assertEqual(BetterDisplayCLI.resolve_app_path(str(cli)), str(app))
            daemon_type = runpy.run_path(str(ROOT / 'bin/padpilotd'))['PadPilotDaemon']
            daemon = daemon_type.__new__(daemon_type)
            daemon.config = Config(betterdisplaycli_path=str(cli))
            # A concurrent CLI helper must not prevent the actual app opening.
            with patch('subprocess.run', side_effect=[subprocess.CompletedProcess([], 1),
                                                    subprocess.CompletedProcess([], 0)]) as launch, \
                 patch('time.sleep'):
                daemon.ensure_betterdisplay_running()
            pattern = launch.call_args_list[0].args[0][-1]
            self.assertIsNotNone(re.search(pattern, str(cli)))
            self.assertIsNone(re.search(pattern, str(cli) + ' get -sidecarList'))
            launch.assert_called_with(['open', '-g', '-n', '-a', str(app)], capture_output=True,
                                      text=True, timeout=10, check=True)
            with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0)) as launch:
                daemon.ensure_betterdisplay_running()
            self.assertEqual(launch.call_count, 1)  # An existing GUI must not be duplicated.

    def test_configuration_and_logs_can_be_removed_independently(self):
        for remove_config, remove_logs in ((True, False), (False, True)):
            with self.subTest(config=remove_config), tempfile.TemporaryDirectory() as directory:
                home = Path(directory).resolve()
                primary = home / 'state'
                fallback = home / 'fallback/config.json'
                logs = home / 'Library/Logs/PadPilot'
                for path in (primary / 'config.json', fallback, logs / 'padpilot.log'):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('keep or trash')
                with patch('pathlib.Path.home', return_value=home), \
                     patch.object(manage_app, 'APP_SUPPORT_DIR', primary), \
                     patch.object(manage_app, 'FALLBACK_CONFIG_FILE', fallback), \
                     patch.object(manage_app, 'installation_service', return_value='notRegistered'), patch.object(manage_app, 'service_command', return_value='notRegistered'), \
                     patch.object(manage_app, 'stop_menu_apps'), patch.object(manage_app, 'ensure_settings_closed'), patch.object(manage_app.subprocess, 'run'):
                    manage_app.manage(uninstall=True, remove_config=remove_config, remove_logs=remove_logs)
                self.assertEqual(primary.exists(), not remove_config)
                self.assertEqual(fallback.exists(), not remove_config)
                self.assertEqual(logs.exists(), not remove_logs)

    def test_custom_path_is_saved_after_stop_and_restored_if_start_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            source = home / 'source'
            (source / 'build/PadPilot.app').mkdir(parents=True)
            cfg = Config(betterdisplaycli_path='/old/cli')
            calls = []
            def run(command, **kwargs):
                calls.append(command)
                if command[-1] == 'set_betterdisplaycli_path':
                    self.assertEqual(calls[-2][-1], 'exit')
                    self.assertEqual(json.loads(kwargs['input']), {'path': '/new/cli'})
                if command[-1] == 'start':
                    raise subprocess.CalledProcessError(1, command)
                return subprocess.CompletedProcess(command, 0)
            with patch('pathlib.Path.home', return_value=home), patch.object(manage_app, 'ROOT', source), \
                 patch.object(manage_app, 'installation_service', return_value='notRegistered'), patch.object(manage_app, 'service_command', return_value='notRegistered'), \
                 patch.object(manage_app, 'build'), patch.object(manage_app, 'load_config', return_value=cfg), \
                 patch.object(manage_app, 'apply_change'), patch.object(manage_app, 'job_loaded', return_value=False), \
                 patch.object(manage_app, 'daemon_pids', return_value=[]), patch.object(manage_app, 'stop_menu_apps'), patch.object(manage_app, 'ensure_settings_closed'), \
                 patch.object(manage_app, 'save_config') as restore, \
                 patch.object(manage_app.subprocess, 'run', side_effect=run):
                with self.assertRaisesRegex(RuntimeError, 'Previous app and service state restored'):
                    manage_app.manage(betterdisplay_path='/new/cli')
                restore.assert_called_once_with(cfg)
            self.assertFalse((home / 'Applications/PadPilot.app').exists())

    def test_unavailable_optional_shortcut_does_not_fail_installed_app(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            source = home / 'source'
            (source / 'build/PadPilot.app').mkdir(parents=True)
            (home / 'bin').write_text('unrelated file')
            with patch('pathlib.Path.home', return_value=home), patch.object(manage_app, 'ROOT', source), \
                 patch.object(manage_app, 'installation_service', return_value='notRegistered'), patch.object(manage_app, 'service_command', return_value='notRegistered'), \
                 patch.object(manage_app, 'build'), patch.object(manage_app, 'load_config', return_value=Config()), \
                 patch.object(manage_app, 'job_loaded', return_value=False), \
                 patch.object(manage_app, 'daemon_pids', return_value=[]), \
                 patch.object(manage_app, 'stop_menu_apps'), patch.object(manage_app, 'ensure_settings_closed'), \
                 patch.object(manage_app.subprocess, 'run'), contextlib.redirect_stdout(io.StringIO()) as output:
                manage_app.manage()
            self.assertTrue((home / 'Applications/PadPilot.app').is_dir())
            self.assertEqual((home / 'bin').read_text(), 'unrelated file')
            self.assertIn('optional CLI shortcut unavailable', output.getvalue())


if __name__ == '__main__':
    unittest.main()
