"""Uninstall consent and ownership checks; never change the real installation."""
import contextlib
import io
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import uninstall_interactive as uninstall


class UninstallInteractiveTests(unittest.TestCase):
    def invoke(self, arguments, answers=(), receipt=None):
        self.manager = types.SimpleNamespace(manage=Mock(), trash=Mock())
        receipt = receipt or {'schema': 1, 'managed_source': False, 'dependencies': []}
        with patch.dict(sys.modules, {'manage_app': self.manager}), \
             patch.object(uninstall, 'read_receipt', return_value=receipt), \
             patch.object(sys.stdin, 'isatty', return_value=bool(answers)), \
             patch('builtins.input', side_effect=answers), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return uninstall.main(arguments)

    def test_no_tty_and_eof_and_final_cancel_do_not_modify_installation(self):
        with self.assertRaises(SystemExit):
            self.invoke(['--purge'])
        self.manager.manage.assert_not_called()
        self.assertEqual(self.invoke([], ['y', EOFError()]), 130)
        self.manager.manage.assert_not_called()
        self.assertEqual(self.invoke([], ['y', 'y', 'n']), 0)
        self.manager.manage.assert_not_called()
        self.assertEqual(self.invoke([], ['q']), 130)
        self.manager.manage.assert_not_called()

    def test_yes_preserves_defaults_and_purge_only_removes_personal_data(self):
        for args, purge in ((['--yes'], False), (['--yes', '--purge'], True)):
            self.assertEqual(self.invoke(args), 0)
            self.manager.manage.assert_called_once_with(uninstall=True, remove_config=purge, remove_logs=purge)
            self.manager.trash.assert_not_called()

    def test_source_and_unrecorded_dependency_requests_fail_closed(self):
        for args in (['--yes', '--remove-source'], ['--yes', '--remove-dependency', 'python@3.14']):
            with self.assertRaises(SystemExit):
                self.invoke(args)
            self.manager.manage.assert_not_called()

    def test_only_managed_source_at_fixed_path_can_be_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            source = home / 'Applications/PadPilot-source'
            source.mkdir(parents=True)
            receipt = {'schema': 1, 'managed_source': True, 'dependencies': []}
            with patch.object(uninstall, 'ROOT', source), patch('pathlib.Path.home', return_value=home):
                self.assertEqual(self.invoke(['--yes', '--remove-source'], receipt=receipt), 0)
                self.manager.trash.assert_called_once_with(source)
                source.rename(source.with_name('other-source'))
                source.symlink_to(source.with_name('other-source'))
                with patch.object(uninstall, 'ROOT', source.resolve()):
                    with self.assertRaises(SystemExit):
                        self.invoke(['--yes', '--remove-source'], receipt=receipt)
                    self.manager.manage.assert_not_called()
                with patch.object(uninstall, 'ROOT', home / 'developer-checkout'):
                    with self.assertRaises(SystemExit):
                        self.invoke(['--yes', '--remove-source'], receipt=receipt)
                    self.manager.manage.assert_not_called()

    def test_betterdisplay_requires_separate_display_disconnect_consent(self):
        receipt = {'schema': 1, 'managed_source': False, 'dependencies': [
            {'name': 'betterdisplay', 'kind': 'cask', 'brew': '/opt/homebrew/bin/brew'}]}
        with self.assertRaises(SystemExit):
            self.invoke(['--yes', '--remove-dependency', 'betterdisplay'], receipt=receipt)
        self.manager.manage.assert_not_called()

    def test_shared_python_is_preserved_and_python_is_removed_last(self):
        with tempfile.TemporaryDirectory() as directory:
            brew = Path(directory) / 'brew'
            brew.write_text('#!/bin/sh\nexit 0\n')
            brew.chmod(0o755)
            receipt = {'schema': 1, 'managed_source': False, 'dependencies': [
                {'name': name, 'kind': kind, 'brew': str(brew)}
                for name, kind in (('python@3.14', 'formula'), ('betterdisplay', 'cask'))]}
            args = ['--yes', '--remove-dependency', 'python@3.14', '--remove-dependency', 'betterdisplay',
                    '--allow-display-disconnect']
            def shared(command, **kwargs):
                return types.SimpleNamespace(stdout='python@3.14 3.14.0\nbetterdisplay 4.0\n'
                                             if command[1] == 'list' else 'other-tool\n')
            with patch.object(uninstall.subprocess, 'run', side_effect=shared):
                self.assertEqual(self.invoke(args, receipt=receipt), 1)
                self.manager.manage.assert_not_called()
            def run(command, **kwargs):
                output = 'python@3.14 3.14.0\nbetterdisplay 4.0\n' if command[1] == 'list' else ''
                return types.SimpleNamespace(stdout=output)
            with patch.object(uninstall.subprocess, 'run', side_effect=run) as runner, \
                 patch.object(uninstall, 'write_receipt') as write:
                self.assertEqual(self.invoke(args, receipt=receipt), 0)
                removals = [call for call in runner.call_args_list if call.args[0][1] == 'uninstall']
                self.assertEqual([call.args[0][2:] for call in removals],
                                 [['--cask', 'betterdisplay'], ['--formula', 'python@3.14']])
                for call in removals:
                    self.assertEqual(call.kwargs['env']['HOMEBREW_NO_AUTOREMOVE'], '1')
                self.assertEqual(write.call_count, 2)

    def test_missing_dependency_is_skipped_and_receipt_is_retired(self):
        with tempfile.TemporaryDirectory() as directory:
            brew = Path(directory) / 'brew'
            brew.write_text('#!/bin/sh\nexit 0\n')
            brew.chmod(0o755)
            receipt = {'schema': 1, 'managed_source': False, 'dependencies': [
                {'name': 'python@3.14', 'kind': 'formula', 'brew': str(brew)}]}
            with patch.object(uninstall.subprocess, 'run', return_value=types.SimpleNamespace(stdout='')) as runner, \
                 patch.object(uninstall, 'write_receipt') as write:
                self.assertEqual(self.invoke(['--yes', '--remove-dependency', 'python@3.14'], receipt=receipt), 0)
                self.assertEqual(runner.call_count, 1)
                self.assertEqual(runner.call_args.args[0][1], 'list')
                self.assertEqual(write.call_args.args[1]['dependencies'], [])

    def test_help_and_cancel_do_not_create_user_state_directories(self):
        for args in (['--help'], []):
            with tempfile.TemporaryDirectory() as directory:
                result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/uninstall_interactive.py'), *args],
                                        input='', capture_output=True, text=True, env={**os.environ, 'HOME': directory})
                self.assertEqual(result.returncode, 0 if args else 2, result.stderr)
                self.assertEqual(list(Path(directory).iterdir()), [])

    @unittest.skipUnless(sys.platform == 'darwin', 'Runtime selection uses macOS plutil')
    def test_shell_uses_recorded_interpreter_with_spaces_instead_of_path_python(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            app = home / 'Applications/PadPilot.app/Contents'
            (app / 'Resources').mkdir(parents=True)
            interpreter = home / 'my python'
            interpreter.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$PADPILOT_TEST_CALLS"\n')
            interpreter.chmod(0o755)
            (app / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.padpilot.app'}))
            (app / 'Resources/runtime.json').write_text(json.dumps({'python': str(interpreter), 'project_root': str(ROOT)}))
            calls = home / 'calls'
            environment = {**os.environ, 'HOME': str(home), 'PATH': '/usr/bin:/bin', 'PADPILOT_TEST_CALLS': str(calls)}
            environment.pop('PADPILOT_PYTHON', None)
            result = subprocess.run(['/bin/bash', str(ROOT / 'scripts/uninstall.sh'), '--yes'],
                                    capture_output=True, text=True, env=environment)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(ROOT / 'scripts/uninstall_interactive.py'), calls.read_text())
            self.assertIn('--yes', calls.read_text())

    @unittest.skipUnless(sys.platform == 'darwin', 'Runtime selection uses macOS plutil')
    def test_shell_retry_without_app_uses_build_or_homebrew_and_skips_old_python(self):
        for preferred in ('build', 'homebrew'):
            with self.subTest(preferred=preferred), tempfile.TemporaryDirectory() as directory:
                home = Path(directory).resolve()
                source = home / 'source'
                scripts = source / 'scripts'
                scripts.mkdir(parents=True)
                (scripts / 'source_runtime.sh').write_text((ROOT / 'scripts/source_runtime.sh').read_text())
                # Relocate fixed discovery paths so this test never depends on the host's Python installations.
                shell = (ROOT / 'scripts/uninstall.sh').read_text().replace('/opt/homebrew/', f'{home}/homebrew/')
                (scripts / 'uninstall.sh').write_text(shell)
                old_python = home / 'path-bin/python3'
                old_python.parent.mkdir()
                old_python.write_text('#!/bin/sh\nexit 1\n')
                old_python.chmod(0o755)
                brew_old = home / 'homebrew/opt/python@3.14/bin/python3.14'
                brew_old.parent.mkdir(parents=True)
                brew_old.symlink_to(old_python)
                interpreter = home / ('build python' if preferred == 'build' else 'homebrew/bin/python3.14')
                interpreter.parent.mkdir(parents=True, exist_ok=True)
                interpreter.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$PADPILOT_TEST_CALLS"\n')
                interpreter.chmod(0o755)
                runtime = source / 'build/PadPilot.app/Contents/Resources/runtime.json'
                runtime.parent.mkdir(parents=True)
                (runtime.parent.parent / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.padpilot.app'}))
                runtime.write_text(json.dumps({'python': str(interpreter if preferred == 'build' else old_python),
                                               'project_root': str(source)}))
                calls = home / 'calls'
                environment = {**os.environ, 'HOME': str(home), 'PATH': f'{old_python.parent}:/usr/bin:/bin',
                               'PADPILOT_TEST_CALLS': str(calls)}
                environment.pop('PADPILOT_PYTHON', None)
                command = ['/bin/bash', str(scripts / 'uninstall.sh'), '--yes', '--purge']
                result = subprocess.run(command, capture_output=True, text=True, env=environment)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(str(scripts / 'uninstall_interactive.py'), calls.read_text())
                self.assertIn('--purge', calls.read_text())
                calls.unlink()
                result = subprocess.run(command, capture_output=True, text=True,
                                        env={**environment, 'PADPILOT_PYTHON': str(old_python)})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('PADPILOT_PYTHON', result.stderr)
                self.assertFalse(calls.exists(), 'An invalid explicit interpreter must not silently fall back')


if __name__ == '__main__':
    unittest.main()
