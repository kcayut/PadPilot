"""Login handshake stays responsive while BetterDisplay is starting."""
import runpy
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core import autostart
from core.betterdisplay import BetterDisplayCLI, BetterDisplayCapabilities
from core.config import Config


Daemon = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'bin/sidecarswitchd'))['SidecarSwitchDaemon']


class DaemonStartupTests(unittest.TestCase):
    def test_slow_dependency_does_not_block_handshake(self):
        probing, release = threading.Event(), threading.Event()

        def slow_probe():
            probing.set()
            if not release.wait(5):
                raise RuntimeError('test dependency was not released')
            return BetterDisplayCapabilities()

        with tempfile.TemporaryDirectory(dir='/tmp', prefix='pp-boot-') as directory:
            endpoint = Path(directory) / 'ipc.sock'
            with patch.dict(Daemon.start.__globals__, SOCKET_PATH=endpoint,
                            load_config=lambda: Config(), DisplayDetector=MagicMock(),
                            remove_state_file=MagicMock(), open_menu_app=MagicMock()), \
                 patch.object(BetterDisplayCLI, '_resolve_cli_path', return_value='/fake/cli'), \
                 patch.object(BetterDisplayCLI, 'probe_capabilities', side_effect=slow_probe) as probe, \
                 patch.object(autostart, 'SOCKET_PATH', endpoint):
                daemon = Daemon()
                probe.assert_not_called()
                daemon.ensure_betterdisplay_running = MagicMock()
                daemon.bd_cli.ensure_virtual_display = MagicMock(return_value=(True, 'OK'))
                daemon.claim_boot_connection = MagicMock(return_value=False)
                daemon.sync_usb_monitor = MagicMock()
                daemon.engine.evaluate = MagicMock(side_effect=lambda **_: daemon.stop())
                worker = threading.Thread(target=daemon.start)
                worker.start()
                try:
                    self.assertTrue(probing.wait(2))
                    autostart.wait_for_daemon(timeout=1)
                    self.assertFalse(release.is_set())
                finally:
                    daemon.stop()
                    release.set()
                    worker.join(3)
                    deadline = time.monotonic() + 2
                    while endpoint.exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                self.assertFalse(worker.is_alive())
                self.assertFalse(endpoint.exists())


if __name__ == '__main__':
    unittest.main()
