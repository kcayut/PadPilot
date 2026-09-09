"""Unit tests for BetterDisplayCLI integration and resilience."""

import unittest
from unittest.mock import MagicMock, patch

from core.betterdisplay import BetterDisplayCLI


class TestBetterDisplayCLI(unittest.TestCase):
    def test_resilience_when_probe_times_out(self) -> None:
        """Verify that when the CLI binary exists, is_available remains True even if probe times out."""
        with patch("os.path.isfile", return_value=True), \
             patch("os.access", return_value=True), \
             patch.object(BetterDisplayCLI, "_resolve_cli_path", return_value="/opt/homebrew/bin/betterdisplaycli"), \
             patch.object(BetterDisplayCLI, "run_cmd", return_value=(-1, "", "Command timed out")):
            cli = BetterDisplayCLI()
            self.assertTrue(cli.is_available())
            self.assertTrue(cli.capabilities.cli_available)
            self.assertFalse(cli.capabilities.sidecar_supported)
            self.assertFalse(cli.capabilities.virtual_creation_supported)

    def test_unavailable_when_binary_not_found(self) -> None:
        """Verify is_available is False when binary path is None or does not exist."""
        with patch.object(BetterDisplayCLI, "_resolve_cli_path", return_value=None):
            cli = BetterDisplayCLI()
            self.assertFalse(cli.is_available())
            self.assertFalse(cli.capabilities.cli_available)

    def test_resolve_cli_path_custom_and_app_bundle(self) -> None:
        """Verify resolve_cli_path resolves direct binaries and app bundle paths."""
        with patch("os.path.isfile", return_value=True), patch("os.access", return_value=True):
            self.assertEqual(
                BetterDisplayCLI.resolve_cli_path("/custom/bin/betterdisplaycli"),
                "/custom/bin/betterdisplaycli"
            )
            self.assertEqual(
                BetterDisplayCLI.resolve_cli_path("/Applications/BetterDisplay.app"),
                "/Applications/BetterDisplay.app/Contents/MacOS/BetterDisplay"
            )

        with patch("os.path.isfile", return_value=False), patch("os.path.isdir", return_value=False):
            self.assertIsNone(BetterDisplayCLI.resolve_cli_path("/nonexistent/betterdisplaycli"))


if __name__ == "__main__":
    unittest.main()
