"""Unit tests for PadPilot CLI flags and metadata."""
import subprocess
import sys
import unittest
from pathlib import Path

from core import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = PROJECT_ROOT / "bin" / "padpilot-cli"


class TestCli(unittest.TestCase):
    def test_cli_version_flag(self):
        res = subprocess.run(
            [sys.executable, str(CLI_PATH), "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn(f"PadPilot {__version__}", res.stdout)

    def test_cli_short_version_flag(self):
        res = subprocess.run(
            [sys.executable, str(CLI_PATH), "-v"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn(f"PadPilot {__version__}", res.stdout)

    def test_cli_help(self):
        res = subprocess.run(
            [sys.executable, str(CLI_PATH), "--help"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("PadPilot Display Manager CLI", res.stdout)
        self.assertIn("--version", res.stdout)
