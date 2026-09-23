"""Unit tests for SidecarSwitch CLI flags and metadata."""
import subprocess
import sys
import unittest
from pathlib import Path

from core import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = PROJECT_ROOT / "bin" / "sidecarswitch-cli"


class TestCli(unittest.TestCase):
    def test_cli_version_flag(self):
        res = subprocess.run(
            [sys.executable, str(CLI_PATH), "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn(f"SidecarSwitch {__version__}", res.stdout)

    def test_cli_short_version_flag(self):
        res = subprocess.run(
            [sys.executable, str(CLI_PATH), "-v"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn(f"SidecarSwitch {__version__}", res.stdout)

    def test_cli_help(self):
        res = subprocess.run(
            [sys.executable, str(CLI_PATH), "--help"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("SidecarSwitch Display Manager CLI", res.stdout)
        self.assertIn("--version", res.stdout)
        self.assertIn("set-language", res.stdout)

    def test_cli_set_language_help_and_validation(self):
        res = subprocess.run(
            [sys.executable, str(CLI_PATH), "set-language", "--help"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("en", res.stdout)
        self.assertIn("zh-Hant", res.stdout)
        self.assertIn("ja", res.stdout)

        # Invalid choice rejected by argparse
        res_invalid = subprocess.run(
            [sys.executable, str(CLI_PATH), "set-language", "fr"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res_invalid.returncode, 0)
        self.assertIn("invalid choice", res_invalid.stderr)
