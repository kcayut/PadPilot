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
