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


if __name__ == "__main__":
    unittest.main()
