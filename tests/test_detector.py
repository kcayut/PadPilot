"""Unit tests for PadPilot Detector and Topology Generation."""

import unittest
from unittest.mock import MagicMock, patch

from core.betterdisplay import BetterDisplayCLI
from core.config import Config
from core.detector import DisplayDetector
from core.models import DisplayInfo, IpadConfig


class TestPadPilotDetector(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config(
            ipad=IpadConfig(name="Cayut iPad", sidecar_uuid="UUID-1234", usb_serial="USB-SERIAL-999"),
            ignore_list=["Dummy", "Virtual"],
            virtual_display_name="PadPilotVirtual",
        )
        self.mock_bd_cli = MagicMock(spec=BetterDisplayCLI)
        self.detector = DisplayDetector(self.config, self.mock_bd_cli)

    def test_display_ignore_filtering(self) -> None:
        """Verify that virtual screens and ignore list matchers are ignored."""
        d1 = DisplayInfo(display_id=1, name="ASUS PG279Q")
        d2 = DisplayInfo(display_id=2, name="PadPilotVirtual")
        d3 = DisplayInfo(display_id=3, name="HDMI Dummy Plug")

        self.assertFalse(self.detector.is_display_ignored(d1))
        self.assertTrue(self.detector.is_display_ignored(d2))
        self.assertTrue(self.detector.is_display_ignored(d3))

    def test_deterministic_topology_signature(self) -> None:
        """Verify deterministic tuple comparison without Python hash() dependency."""
        d1 = DisplayInfo(display_id=10, name="ASUS Monitor")
        d2 = DisplayInfo(display_id=2, name="Dell Monitor")

        sig1 = (tuple(sorted([d1.display_id, d2.display_id])), True)
        sig2 = (tuple(sorted([d2.display_id, d1.display_id])), True)

        self.assertEqual(sig1, ( (2, 10), True ))
        self.assertEqual(sig1, sig2)

    def test_usb_parsing_with_configured_serial(self) -> None:
        """Verify exact USB serial matching for configured iPad."""
        mock_ioreg = """
+-o AppleT8132USBXHCI@00000000 <class AppleT8132USBXHCI>
+-o iPad@01100000 <class IOUSBHostDevice>
    {
      "idVendor" = 1452
      "idProduct" = 4780
      "kUSBSerialNumberString" = "USB-SERIAL-999"
      "kUSBProductString" = "iPad"
    }
"""
        with patch("subprocess.check_output", return_value=mock_ioreg):
            devices = self.detector.parse_usb_devices()
            self.assertEqual(len(devices), 1)
            self.assertEqual(devices[0]["serial"], "USB-SERIAL-999")
            self.assertEqual(devices[0]["vendor_id"], 1452)

    def test_vendor_2198_virtual_display_detection(self) -> None:
        """Verify that displays with BetterDisplay vendor 2198 are recognized as virtual."""
        import ctypes

        def mock_get_online_displays(max_d, d_ids, count_ref):
            d_ids[0] = 100
            ctypes.cast(count_ref, ctypes.POINTER(ctypes.c_uint32))[0] = 1
            return 0

        # Setup mock CoreGraphics
        mock_cg = MagicMock()
        mock_cg.CGGetOnlineDisplayList.side_effect = mock_get_online_displays
        mock_cg.CGDisplayIsActive.return_value = 1
        mock_cg.CGDisplayIsMain.return_value = 1
        mock_cg.CGDisplayIsBuiltin.return_value = 0
        mock_cg.CGDisplayPixelsWide.return_value = 1920
        mock_cg.CGDisplayPixelsHigh.return_value = 1080
        mock_cg.CGDisplayVendorNumber.return_value = 2198
        mock_cg.CGDisplayModelNumber.return_value = 5094

        self.detector._cg = mock_cg
        self.mock_bd_cli.get_display_identifiers.return_value = []

        displays = self.detector.get_online_displays()
        self.assertEqual(len(displays), 1)
        self.assertTrue(displays[0].is_virtual)
        self.assertEqual(displays[0].name, "PadPilotVirtual")

    def test_ghost_headless_display_ignored(self) -> None:
        """Verify that 0x0, inactive, or vendor 0 headless placeholder displays are filtered out."""
        import ctypes

        def mock_get_online_displays(max_d, d_ids, count_ref):
            d_ids[0] = 1
            ctypes.cast(count_ref, ctypes.POINTER(ctypes.c_uint32))[0] = 1
            return 0

        mock_cg = MagicMock()
        mock_cg.CGGetOnlineDisplayList.side_effect = mock_get_online_displays
        # Inactive or 0x0
        mock_cg.CGDisplayIsActive.return_value = 0
        mock_cg.CGDisplayIsMain.return_value = 1
        mock_cg.CGDisplayIsBuiltin.return_value = 0
        mock_cg.CGDisplayPixelsWide.return_value = 0
        mock_cg.CGDisplayPixelsHigh.return_value = 0
        mock_cg.CGDisplayVendorNumber.return_value = 0
        mock_cg.CGDisplayModelNumber.return_value = 0

        self.detector._cg = mock_cg
        self.mock_bd_cli.get_display_identifiers.return_value = []

        displays = self.detector.get_online_displays()
        self.assertEqual(len(displays), 0)


if __name__ == "__main__":
    unittest.main()
