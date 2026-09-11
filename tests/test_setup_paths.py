"""Installer path selection and independent data removal, with no live services."""
import contextlib
import io
import json
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
    def test_open_settings_or_failed_process_query_blocks_changes(self):
        for code in (0, 2):
            with patch.object(manage_app.subprocess, 'run', return_value=subprocess.CompletedProcess([], code)):
                with self.assertRaises(RuntimeError):
                    manage_app.ensure_settings_closed()
        with patch.object(manage_app.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)):
            manage_app.ensure_settings_closed()

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
            with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1)), \
                 patch('subprocess.Popen') as launch, patch('time.sleep'):
                daemon.ensure_betterdisplay_running()
            launch.assert_called_once_with(['open', '-a', str(app)])

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
                     patch.object(manage_app, 'get_launch_agent_plist_path', return_value=home / 'absent.plist'), \
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
                 patch.object(manage_app, 'get_launch_agent_plist_path', return_value=home / 'absent.plist'), \
                 patch.object(manage_app, 'build'), patch.object(manage_app, 'load_config', return_value=cfg), \
                 patch.object(manage_app, 'apply_change'), patch.object(manage_app, 'job_loaded', return_value=False), \
                 patch.object(manage_app, 'daemon_pids', return_value=[]), patch.object(manage_app, 'stop_menu_apps'), patch.object(manage_app, 'ensure_settings_closed'), \
                 patch.object(manage_app, 'stop_daemon'), patch.object(manage_app, 'save_config') as restore, \
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
                 patch.object(manage_app, 'get_launch_agent_plist_path', return_value=home / 'absent.plist'), \
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
