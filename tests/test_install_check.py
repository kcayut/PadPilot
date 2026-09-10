"""Installer tests use temporary user directories and fake external commands."""
import builtins
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import check_install


class InstallCheckTests(unittest.TestCase):
    def test_preflight_warns_for_tk_and_does_not_create_user_files(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            original_import = builtins.__import__
            def without_tk(name, *args, **kwargs):
                if name == 'tkinter':
                    raise ImportError('no Tk')
                return original_import(name, *args, **kwargs)
            with patch('pathlib.Path.home', return_value=home), \
                 patch.object(check_install.platform, 'mac_ver', return_value=('14.0', (), 'arm64')), \
                 patch.object(check_install.sys, 'platform', 'darwin'), \
                 patch('pathlib.Path.is_dir', return_value=True), \
                 patch.object(check_install.BetterDisplayCLI, 'resolve_cli_path', return_value='/fake/cli'), \
                 patch('builtins.__import__', side_effect=without_tk), \
                 patch.object(check_install.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'help', '')), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertTrue(check_install.check())
            self.assertIn('WARN: Tkinter', output.getvalue())
            self.assertEqual(list(home.iterdir()), [])

    def test_missing_cli_or_failed_help_fails_preflight(self):
        for cli, code in ((None, 0), ('/fake/cli', 1)):
            with tempfile.TemporaryDirectory() as directory, \
                 patch('pathlib.Path.home', return_value=Path(directory)), \
                 patch.object(check_install.BetterDisplayCLI, 'resolve_cli_path', return_value=cli), \
                 patch.object(check_install.subprocess, 'run', return_value=subprocess.CompletedProcess([], code, '', 'unavailable')), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertFalse(check_install.check())
                self.assertIn('FAIL: BetterDisplay CLI', output.getvalue())

    def test_read_only_check_rejects_symlink_config_without_executing_its_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            root = home / 'Library/Application Support/PadPilot'
            root.mkdir(parents=True)
            outside = home / 'outside.json'
            outside.write_text('{"betterdisplaycli_path":"/untrusted/cli"}')
            outside.chmod(0o644)
            (root / 'config.json').symlink_to(outside)
            with patch('pathlib.Path.home', return_value=home), \
                 patch.object(check_install.BetterDisplayCLI, 'resolve_cli_path', return_value=None) as resolve, \
                 patch.object(check_install.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'swiftc', '')), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertFalse(check_install.check())
            resolve.assert_called_once_with(None)
            self.assertIn('FAIL: Configuration', output.getvalue())
            self.assertEqual(outside.stat().st_mode & 0o777, 0o644)

    def test_invalid_cli_value_is_reported_without_passing_it_to_resolver(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / 'Library/Application Support/PadPilot/config.json'
            path.parent.mkdir(parents=True)
            path.write_text('{"betterdisplaycli_path": ["invalid"]}')
            with patch('pathlib.Path.home', return_value=home), \
                 patch.object(check_install.BetterDisplayCLI, 'resolve_cli_path', return_value=None) as resolve, \
                 patch.object(check_install.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'swiftc', '')), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertFalse(check_install.check())
            resolve.assert_called_once_with(None)
            self.assertIn('FAIL: Configuration', output.getvalue())

    def test_shell_check_never_installs_or_starts_and_failure_stops_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / 'bin'
            fake_bin.mkdir()
            record = root / 'commands.log'
            python = fake_bin / 'python3'
            # External command stubs, never execute the real setup or brew.
            python.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$PADPILOT_TEST_RECORD"\nexit 7\n')
            python.chmod(0o755)
            brew = fake_bin / 'brew'
            brew.write_text('#!/bin/sh\nprintf "UNEXPECTED BREW\\n" >> "$PADPILOT_TEST_RECORD"\nexit 9\n')
            brew.chmod(0o755)
            env = dict(os.environ, PATH=str(fake_bin) + ':/usr/bin:/bin', HOME=str(root / 'user'),
                       PADPILOT_TEST_RECORD=str(record))
            for flag in ('--check', '--yes'):
                record.unlink(missing_ok=True)
                result = subprocess.run(['bash', str(ROOT / 'scripts/install.sh'), flag], env=env,
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                calls = record.read_text()
                self.assertNotIn('manage_app.py', calls)
                self.assertNotIn('UNEXPECTED BREW', calls)
                self.assertNotIn('Installed:', result.stdout)
                self.assertFalse((root / 'user').exists())

    def test_missing_betterdisplay_refusal_and_brew_failure_never_succeed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / 'bin'
            fake_bin.mkdir()
            record = root / 'commands.log'
            installer = root / 'install.sh'
            # Isolate the fixed system app lookup as well as HOME and commands.
            installer.write_text((ROOT / 'scripts/install.sh').read_text().replace(
                '/Applications/BetterDisplay.app', '/Applications/PadPilot-Test-Missing.app'))
            for name, body in (('python3', 'exit 0'), ('brew', 'exit 9')):
                command = fake_bin / name
                command.write_text(f'#!/bin/sh\nprintf "{name} %s\\n" "$*" >> "$PADPILOT_TEST_RECORD"\n{body}\n')
                command.chmod(0o755)
            env = dict(os.environ, PATH=str(fake_bin) + ':/usr/bin:/bin', HOME=str(root / 'user'),
                       PADPILOT_TEST_RECORD=str(record))
            for answer, brew_expected in (('n\n', False), ('y\n', True)):
                record.unlink(missing_ok=True)
                result = subprocess.run(['bash', str(installer)], input=answer, env=env,
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                calls = record.read_text()
                self.assertEqual('brew install --cask betterdisplay' in calls, brew_expected)
                self.assertNotIn('manage_app.py', calls)
                self.assertNotIn('Installed:', result.stdout)
                self.assertFalse((root / 'user').exists())


if __name__ == '__main__':
    unittest.main()
