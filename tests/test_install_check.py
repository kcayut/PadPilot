"""Installer tests use temporary user directories and fake external commands."""
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
    def test_preflight_never_creates_user_files(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch('pathlib.Path.home', return_value=home), \
                 patch.object(check_install.platform, 'mac_ver', return_value=('14.0', (), 'arm64')), \
                 patch.object(check_install.sys, 'platform', 'darwin'), \
                 patch('pathlib.Path.is_dir', return_value=True), \
                 patch.object(check_install.BetterDisplayCLI, 'resolve_cli_path', return_value='/fake/cli'), \
                 patch.object(check_install.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'help', '')), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertTrue(check_install.check())
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

    @contextlib.contextmanager
    def shell_setup(self, **overrides):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / 'bin with spaces'
            fake_bin.mkdir()
            state = root / 'packages'
            state.mkdir()
            record = root / 'commands.log'
            commands = {
                'uname': 'echo Darwin',
                'sw_vers': 'echo 14.7',
                'xcrun': 'exit "${PADPILOT_TEST_CLT:-0}"',
                'xcode-select': 'echo "xcode-select $*" >> "$PADPILOT_TEST_RECORD"; exit "${PADPILOT_TEST_CLT_SELECT:-0}"',
                'plutil': 'case "$*" in *CFBundleIdentifier*) echo com.padpilot.app ;; *project_root*) echo "$PADPILOT_TEST_ROOT" ;; *python*) echo "$PADPILOT_TEST_RUNTIME_PYTHON" ;; esac',
                'python3': r'''for last do :; done
printf 'python %s\n' "$*" >> "$PADPILOT_TEST_RECORD"
case "$*" in
    *'import sys; sys.exit'*)
        case "$0" in */python3.14) [ ! -f "$PADPILOT_TEST_STATE/python@3.14" ] || exit 0 ;; esac
        exit "${PADPILOT_TEST_PYTHON:-0}" ;;
    *resolve_betterdisplay_path*)
        if [ -n "$last" ]; then printf '%s\n' "$last"; else printf '%s\n' "${PADPILOT_TEST_BD:-}"; fi ;;
    *check_install.py*) exit "${PADPILOT_TEST_CHECK:-0}" ;;
esac
exit 0''',
                'brew': r'''for last do :; done
printf 'brew %s\n' "$*" >> "$PADPILOT_TEST_RECORD"
case "$1" in
    list) [ -f "$PADPILOT_TEST_STATE/$last" ] || exit 1; echo "$last 3.14" ;;
    install)
        if [ "${PADPILOT_TEST_BREW_FAIL:-}" = "$last" ]; then
            if [ "${PADPILOT_TEST_BREW_PARTIAL:-0}" = 1 ]; then touch "$PADPILOT_TEST_STATE/$last"; fi
            exit 9
        fi
        touch "$PADPILOT_TEST_STATE/$last" ;;
    --prefix) printf '%s\n' "$PADPILOT_TEST_PREFIX" ;;
esac''',
            }
            for name, body in commands.items():
                command = fake_bin / name
                command.write_text('#!/bin/sh\n' + body + '\n')
                command.chmod(0o755)
            prefix = fake_bin / 'prefix'
            (prefix / 'bin').mkdir(parents=True)
            (prefix / 'bin/python3.14').symlink_to(fake_bin / 'python3')
            (fake_bin / 'saved-python').symlink_to(fake_bin / 'python3')
            env = dict(os.environ, PATH=str(fake_bin) + ':/usr/bin:/bin', HOME=str(root / 'user'),
                       PADPILOT_TEST_RECORD=str(record), PADPILOT_TEST_STATE=str(state),
                       PADPILOT_TEST_PREFIX=str(prefix), PADPILOT_TEST_BD='/custom/BetterDisplay.app',
                       PADPILOT_TEST_ROOT=str(ROOT), PADPILOT_TEST_RUNTIME_PYTHON=str(fake_bin / 'saved-python'))
            env.update(overrides)
            def run(*args, answer=None, use_saved=False):
                record.unlink(missing_ok=True)
                python_args = [] if use_saved else ['--python', str(fake_bin / 'python3')]
                result = subprocess.run(['/bin/bash', str(ROOT / 'scripts/install.sh'),
                                         *python_args, *args],
                                        input=answer, env=env, capture_output=True, text=True)
                return result, record.read_text() if record.exists() else ''
            yield root, state, run

    def test_shell_check_never_installs_or_starts_and_failure_stops_install(self):
        with self.shell_setup(PADPILOT_TEST_CHECK='7') as (root, _, run):
            for flag in ('--check', '--yes'):
                result, calls = run(flag)
                self.assertEqual(result.returncode, 7, result.stderr)
                self.assertNotIn('manage_app.py', calls)
                self.assertNotIn('brew ', calls)
                self.assertNotIn('setup_state.py --record', calls)
                self.assertNotIn('Installed:', result.stdout)
                self.assertFalse((root / 'user').exists())

    def test_missing_betterdisplay_refusal_and_brew_failure_never_succeed(self):
        with self.shell_setup(PADPILOT_TEST_BD='', PADPILOT_TEST_BREW_FAIL='betterdisplay') as (root, _, run):
            result, calls = run('--yes')
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('brew ', calls)
            self.assertNotIn('manage_app.py', calls)
            result, calls = run('--yes', '--install-deps')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('brew install --cask betterdisplay', calls)
            self.assertNotIn('setup_state.py --record', calls)
            self.assertNotIn('manage_app.py', calls)
            self.assertFalse((root / 'user').exists())

    def test_yes_installs_with_selected_paths_and_never_calls_brew(self):
        with self.shell_setup() as (_, _, run):
            selected = '/Users/example/Custom BetterDisplay.app'
            result, calls = run('--yes', '--betterdisplay-path', selected)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('check_install.py --betterdisplay-path ' + selected, calls)
            self.assertIn('manage_app.py --betterdisplay-path ' + selected, calls)
            self.assertNotIn('brew ', calls)

    def test_interactive_manual_path_and_confirmation(self):
        with self.shell_setup(PADPILOT_TEST_BD='') as (_, _, run):
            result, calls = run(answer='\nm\n/custom/My BetterDisplay.app\n\n\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('manage_app.py --betterdisplay-path /custom/My BetterDisplay.app', calls)
            self.assertNotIn('brew ', calls)

    def test_reinstall_prefers_the_installed_apps_python(self):
        with self.shell_setup() as (root, _, run):
            runtime = root / 'user/Applications/PadPilot.app/Contents/Resources/runtime.json'
            runtime.parent.mkdir(parents=True)
            runtime.write_text('{}')  # plutil is stubbed with this checkout's runtime values.
            result, _ = run('--yes', use_saved=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('saved-python', result.stdout)

    def test_unknown_options_stop_before_dependency_checks_or_installation(self):
        with self.shell_setup() as (_, _, run):
            for option in ('--headless', '--unknown'):
                result, calls = run('--yes', option)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn('unknown option', result.stderr)
                self.assertEqual(calls, '')

    def test_new_python_is_recorded_before_failed_betterdisplay_install(self):
        with self.shell_setup(PADPILOT_TEST_PYTHON='1', PADPILOT_TEST_BD='',
                              PADPILOT_TEST_BREW_FAIL='betterdisplay') as (_, _, run):
            result, calls = run('--yes', '--install-deps')
            self.assertNotEqual(result.returncode, 0)
            recorded = 'setup_state.py --record-dependency formula python@3.14'
            self.assertIn(recorded, calls)
            self.assertLess(calls.index(recorded), calls.index('brew install --cask betterdisplay'))
            self.assertNotIn('setup_state.py --record-dependency cask betterdisplay', calls)
            self.assertNotIn('manage_app.py', calls)

    def test_missing_python_installs_and_records_python(self):
        with self.shell_setup(PADPILOT_TEST_PYTHON='1') as (_, _, run):
            result, calls = run('--yes', '--install-deps')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('setup_state.py --record-dependency formula python@3.14', calls)
            self.assertIn('manage_app.py', calls)

    def test_preexisting_python_is_not_claimed_when_user_reinstalls_it(self):
        with self.shell_setup() as (_, state, run):
            (state / 'python@3.14').touch()
            result, calls = run(answer='i\n\n\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('brew install --formula python@3.14', calls)
            self.assertNotIn('setup_state.py --record-dependency formula python@3.14', calls)
            self.assertIn('manage_app.py', calls)

    def test_partly_successful_brew_failure_records_installed_dependency(self):
        with self.shell_setup(PADPILOT_TEST_BD='', PADPILOT_TEST_BREW_FAIL='betterdisplay',
                              PADPILOT_TEST_BREW_PARTIAL='1') as (_, _, run):
            result, calls = run('--yes', '--install-deps')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('setup_state.py --record-dependency cask betterdisplay', calls)
            self.assertNotIn('manage_app.py', calls)

    def test_missing_clt_requires_opt_in_and_waits_for_apple_install(self):
        with self.shell_setup(PADPILOT_TEST_CLT='1') as (_, _, run):
            result, calls = run('--yes')
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('xcode-select --install', calls)
            result, calls = run('--yes', '--install-deps')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('xcode-select --install', calls)
            self.assertNotIn('brew ', calls)
            self.assertNotIn('manage_app.py', calls)

    def test_receipt_is_read_only_then_appends_only_once(self):
        import setup_state
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = setup_state.read_receipt(root)
            self.assertEqual(list(root.iterdir()), [])
            receipt['managed_source'] = True
            setup_state.write_receipt(root, receipt)
            for _ in range(2):
                setup_state.record_dependency(root, 'formula', 'python@3.14', '/opt/homebrew/bin/brew')
            result = setup_state.read_receipt(root)
            self.assertTrue(result['managed_source'])
            self.assertEqual(len(result['dependencies']), 1)
            self.assertEqual((root / '.padpilot-install.json').stat().st_mode & 0o777, 0o600)
            outside = root / 'outside.json'
            (root / '.padpilot-install.json').rename(outside)
            (root / '.padpilot-install.json').symlink_to(outside)
            with self.assertRaises(RuntimeError):
                setup_state.read_receipt(root)
            self.assertEqual(len(json.loads(outside.read_text())['dependencies']), 1)


if __name__ == '__main__':
    unittest.main()
