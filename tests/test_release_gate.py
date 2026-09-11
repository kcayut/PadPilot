"""Separating CI jobs must not silently waive the release privacy gate."""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import check_release


class ReleaseGateTests(unittest.TestCase):
    def test_uninstall_syntax_failure_blocks_the_software_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            (root / 'scripts/install.sh').write_text('#!/bin/bash\nexit 0\n')
            (root / 'scripts/uninstall.sh').write_text('#!/bin/bash\nif then\n')
            real_run = subprocess.run
            def run(command, **kwargs):
                return real_run(command, **kwargs) if command[0] == 'bash' else subprocess.CompletedProcess(command, 0, '', '')
            with patch.object(check_release, 'ROOT', root), patch.object(check_release, 'check_versions'), \
                 patch.object(check_release, 'scan_privacy', return_value={'tree': [], 'history': []}), \
                 patch.object(check_release.subprocess, 'run', side_effect=run), \
                 patch.object(sys, 'argv', ['check_release.py', '--software-only']), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(check_release.main(), 1)
            checks = json.loads((root / 'build/release-check.json').read_text())['checks']
            self.assertEqual(checks['install_shell_syntax'], 'pass')
            self.assertEqual(checks['uninstall_shell_syntax'], 'fail')

    def test_history_exceptions_are_exact_and_never_hide_current_files(self):
        private_path = '/Users/' + 'sample-person/project'
        accepted = sorted(check_release.ACCEPTED_HISTORY)
        self.assertEqual(len(accepted), 6)
        patches = ''.join(f'COMMIT {commit}\n+++ b/{path}\n+{private_path}\n'
                          for _, commit, path in accepted)
        commit = accepted[0][1]
        patches += (f'COMMIT new-commit\n+++ b/README.md\n+{private_path}\n'
                    f'COMMIT {commit}\n+++ b/other.md\n+{private_path}\n'
                    f'COMMIT {commit}\n+++ b/README.md\n+gh' + 'p_' + 'A' * 36 + '\n')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'README.md').write_text(private_path)
            with patch.object(check_release, 'ROOT', root), \
                 patch.object(check_release.subprocess, 'check_output',
                              side_effect=[b'README.md\0', patches.encode()]):
                report = check_release.scan_privacy()
        self.assertEqual(len(report['accepted_history']), 6)
        self.assertEqual(len(report['history']), 3)
        self.assertEqual(report['tree'], [{'kind': 'private_path', 'path': 'README.md', 'line': 1}])
        self.assertNotIn(private_path, json.dumps(report))

    def test_scan_only_accepts_reviewed_history_but_blocks_new_findings(self):
        for field in (None, 'tree', 'history'):
            report = {'tree': [], 'history': [], 'accepted_history': [{'kind': 'private_path'}]}
            if field:
                report[field].append({'kind': 'private_path'})
            with tempfile.TemporaryDirectory() as directory, \
                 patch.object(check_release, 'ROOT', Path(directory)), \
                 patch.object(sys, 'argv', ['check_release.py', '--scan-only']), \
                 patch.object(check_release, 'scan_privacy', return_value=report), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(check_release.main(), 1 if field else 0)

    def test_software_mode_never_claims_release_ready_or_hides_software_failure(self):
        for flags, command_code, expected in (([], 0, 1), (['--software-only'], 0, 0),
                                               (['--software-only'], 1, 1)):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with patch.object(check_release, 'ROOT', root), \
                     patch.object(sys, 'argv', ['check_release.py', *flags]), \
                     patch.object(check_release, 'scan_privacy', return_value={
                         'tree': [], 'history': [{'kind': 'private_path'}]}), \
                     patch.object(check_release, 'check_versions'), \
                     patch.object(check_release.subprocess, 'run', return_value=
                                  subprocess.CompletedProcess([], command_code, '', '')), \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(check_release.main(), expected)
                report = json.loads((root / 'build/release-check.json').read_text())
                self.assertEqual(report['privacy'], 'review_required')
                self.assertFalse(report['stable_ready'])


if __name__ == '__main__':
    unittest.main()
