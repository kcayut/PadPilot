"""Unit tests for PadPilot LaunchAgent Autostart Manager."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.autostart import (
    disable_autostart,
    enable_autostart,
    generate_plist_content,
    is_autostart_enabled,
    is_swiftbar_recovery_bug_present,
    notify_swiftbar,
    toggle_autostart,
)
from core.config import Config


class TestPadPilotAutostart(unittest.TestCase):
    def setUp(self) -> None:
        for target, kwargs in (
            ("core.autostart.load_config", {"side_effect": Config}),
            ("core.autostart.save_config", {}),
            ("core.autostart.is_daemon_running", {"return_value": False}),
        ):
            mocked = patch(target, **kwargs)
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_config_autostart_field(self) -> None:
        cfg = Config()
        self.assertTrue(cfg.autostart_on_login)

        cfg_dict = cfg.to_dict()
        self.assertIn("autostart_on_login", cfg_dict)
        self.assertTrue(cfg_dict["autostart_on_login"])

        cfg_dict["autostart_on_login"] = False
        loaded = Config.from_dict(cfg_dict)
        self.assertFalse(loaded.autostart_on_login)

    def test_generate_plist_content(self) -> None:
        custom_py = "/usr/local/bin/python3"
        custom_root = Path("/opt/PadPilot")
        custom_logs = Path("/var/log/PadPilot")

        xml = generate_plist_content(
            python_bin=custom_py,
            project_root=custom_root,
            log_dir=custom_logs,
        )

        self.assertIn("<string>com.padpilot.daemon</string>", xml)
        self.assertIn(f"<string>{custom_py}</string>", xml)
        self.assertIn(f"<string>{custom_root / 'bin' / 'padpilotd'}</string>", xml)
        self.assertIn(f"<string>{custom_logs / 'launchd.stdout.log'}</string>", xml)
        self.assertIn("<key>RunAtLoad</key>", xml)
        self.assertIn("<key>KeepAlive</key>", xml)

    def test_is_autostart_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            test_plist = Path(tmpdir) / "test.plist"
            self.assertFalse(is_autostart_enabled(test_plist))

            test_plist.write_text("<plist></plist>", encoding="utf-8")
            self.assertTrue(is_autostart_enabled(test_plist))

    @patch("core.autostart.notify_swiftbar")
    @patch("subprocess.run")
    def test_enable_and_disable_autostart(self, mock_run: MagicMock, mock_notify: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        with tempfile.TemporaryDirectory() as tmpdir:
            test_plist = Path(tmpdir) / "com.padpilot.daemon.plist"

            # 1. Enable autostart
            ok, msg = enable_autostart(plist_path=test_plist)
            self.assertTrue(ok)
            self.assertTrue(test_plist.is_file())
            self.assertTrue(is_autostart_enabled(test_plist))

            # 2. Disable autostart
            with patch("core.autostart.is_daemon_running", return_value=False):
                ok, msg = disable_autostart(plist_path=test_plist)
                self.assertTrue(ok)
                self.assertFalse(test_plist.is_file())
                self.assertFalse(is_autostart_enabled(test_plist))

    @patch("core.autostart.notify_swiftbar")
    @patch("subprocess.run")
    def test_toggle_autostart(self, mock_run: MagicMock, mock_notify: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        with tempfile.TemporaryDirectory() as tmpdir:
            test_plist = Path(tmpdir) / "com.padpilot.daemon.plist"

            with patch("core.autostart.is_daemon_running", return_value=False):
                # Start disabled -> toggle -> enabled
                self.assertFalse(is_autostart_enabled(test_plist))
                ok, _ = toggle_autostart(plist_path=test_plist)
                self.assertTrue(ok)
                self.assertTrue(is_autostart_enabled(test_plist))

                # Enabled -> toggle -> disabled
                ok, _ = toggle_autostart(plist_path=test_plist)
                self.assertTrue(ok)
                self.assertFalse(is_autostart_enabled(test_plist))

    @patch("subprocess.Popen")
    def test_notify_swiftbar_url_format_immediate(self, mock_popen: MagicMock) -> None:
        notify_swiftbar("padpilot.30s.py", delay=0.0)
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        self.assertEqual(cmd, ["open", "-g", "swiftbar://refreshallplugins"])

    @patch("subprocess.Popen")
    def test_notify_swiftbar_debounce_single_flight(self, mock_popen: MagicMock) -> None:
        # Rapid multiple calls within 20ms should coalesce to 1 Popen call
        notify_swiftbar("padpilot.30s.py", delay=0.05)
        notify_swiftbar("padpilot.30s.py", delay=0.05)
        notify_swiftbar("padpilot.30s.py", delay=0.05)
        self.assertEqual(mock_popen.call_count, 0)
        time.sleep(0.1)
        self.assertEqual(mock_popen.call_count, 1)

    @patch("subprocess.Popen")
    def test_debounce_is_thread_safe_under_concurrent_notifications(self, mock_popen: MagicMock) -> None:
        import concurrent.futures
        # Call 10 times concurrently across threads
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(notify_swiftbar, "padpilot.30s.py", 0.05) for _ in range(10)]
            for f in futures:
                f.result()
        time.sleep(0.1)
        self.assertEqual(mock_popen.call_count, 1)



if __name__ == "__main__":
    unittest.main()
