"""Comprehensive unit tests for PadPilot StateEngine covering all 10 scenarios."""

import time
import unittest
from unittest.mock import MagicMock, patch

from core.betterdisplay import BetterDisplayCLI
from core.config import Config
from core.detector import DisplayDetector
from core.models import (
    ActualState,
    DesiredState,
    DisplayInfo,
    DisplayRole,
    IpadConfig,
    OperationMode,
    TransitionState,
    UserOverride,
)
from core.state_engine import StateEngine


class TestPadPilotStateMachine(unittest.TestCase):
    def setUp(self) -> None:
        export = patch.object(StateEngine, "_export_status")
        export.start()
        self.addCleanup(export.stop)
        self.config = Config(
            mode=OperationMode.AUTOMATIC,
            ipad=IpadConfig(name="Cayut iPad", sidecar_uuid="1111-2222-3333", usb_serial="USB12345"),
            debounce_seconds=4.0,
            max_retries=3,
            retry_interval=0.01,
            cooldown_seconds=30.0,
        )
        self.mock_bd_cli = MagicMock(spec=BetterDisplayCLI)
        self.mock_detector = MagicMock(spec=DisplayDetector)
        self.default_actual = ActualState()
        self.mock_detector.observe.return_value = (self.default_actual, ((), False))
        self.engine = StateEngine(self.config, self.mock_detector, self.mock_bd_cli)

    def test_scenario_1_desktop_mode(self) -> None:
        """Scenario 1: Physical monitor connected + USB iPad connected + Auto Mode
        Result: Sidecar does not auto-start, physical display remains main.
        """
        phys_disp = DisplayInfo(display_id=1, name="ASUS PG279Q", is_main=True)
        actual = ActualState(
            physical_displays=[phys_disp],
            main_display=phys_disp,
            ipad_usb_present=True,
            sidecar_connected=False,
            sidecar_display_online=False,
        )
        desired = self.engine.policy(actual, self.config, self.engine.runtime)

        self.assertEqual(desired.target_display_role, DisplayRole.PHYSICAL)
        self.assertFalse(desired.needs_sidecar_connect)
        self.assertTrue(self.engine.is_satisfied(actual, desired))
        self.assertIn("Physical display detected", desired.reason)

    def test_scenario_2_outdoor_headless_mode(self) -> None:
        """Scenario 2: No physical monitor + USB iPad connected + Auto Mode
        Result: Sidecar connects automatically, iPad set as Main.
        """
        actual = ActualState(
            physical_displays=[],
            main_display=None,
            ipad_usb_present=True,
            sidecar_connected=False,
            sidecar_display_online=False,
        )
        desired = self.engine.policy(actual, self.config, self.engine.runtime)

        self.assertEqual(desired.target_display_role, DisplayRole.IPAD_MAIN)
        self.assertTrue(desired.needs_sidecar_connect)
        self.assertEqual(desired.needs_main_display_target, "ipad")
        self.assertFalse(self.engine.is_satisfied(actual, desired))

    def test_scenario_3_user_override_secondary(self) -> None:
        """Scenario 3: Physical monitor connected + user selects 'Use iPad as Secondary'
        Result: Physical remains Main, iPad becomes Secondary, Automation does not overwrite.
        """
        self.engine.runtime.topology_generation = 5
        self.engine.set_user_override(DisplayRole.IPAD_SECONDARY, async_transition=False)

        phys_disp = DisplayInfo(display_id=1, name="ASUS PG279Q", is_main=True)
        ipad_disp = DisplayInfo(display_id=2, name="Cayut iPad", is_main=False, is_sidecar=True)
        actual = ActualState(
            physical_displays=[phys_disp],
            main_display=phys_disp,
            ipad_usb_present=True,
            sidecar_connected=True,
            sidecar_display_online=True,
            topology_generation=5,
        )

        desired = self.engine.policy(actual, self.config, self.engine.runtime)
        self.assertEqual(desired.target_display_role, DisplayRole.IPAD_SECONDARY)
        self.assertTrue(self.engine.is_satisfied(actual, desired))

    def test_scenario_4_physical_monitor_unplugged_expires_override(self) -> None:
        """Scenario 4: From Scenario 3, physical monitor is unplugged.
        Result: Topology generation changes, override expires, auto switches to iPad Main.
        """
        self.engine.runtime.topology_generation = 5
        self.engine.set_user_override(DisplayRole.IPAD_SECONDARY, async_transition=False)

        # Monitor is unplugged -> generation increments to 6
        self.engine.runtime.topology_generation = 6

        actual = ActualState(
            physical_displays=[],
            main_display=None,
            ipad_usb_present=True,
            sidecar_connected=False,
            sidecar_display_online=False,
            topology_generation=6,
        )

        desired = self.engine.policy(actual, self.config, self.engine.runtime)
        # Override expired! Now targets IPAD_MAIN
        self.assertIsNone(self.engine.runtime.user_override)
        self.assertEqual(desired.target_display_role, DisplayRole.IPAD_MAIN)

    def test_scenario_5_completely_headless_fallback(self) -> None:
        """Scenario 5: No physical monitor + No iPad
        Result: Fallback to BetterDisplay Virtual Display.
        """
        v_disp = DisplayInfo(display_id=99, name="PadPilotVirtual", is_main=True, is_virtual=True)
        actual = ActualState(
            physical_displays=[],
            main_display=v_disp,
            virtual_display_exists=True,
            virtual_display_connected=True,
            ipad_usb_present=False,
            sidecar_connected=False,
        )

        desired = self.engine.policy(actual, self.config, self.engine.runtime)
        self.assertEqual(desired.target_display_role, DisplayRole.VIRTUAL)
        self.assertTrue(self.engine.is_satisfied(actual, desired))

    def test_scenario_6_sidecar_retry_and_cooldown(self) -> None:
        """Scenario 6: Sidecar connection failure -> Retries up to 3 times -> Enters cooldown."""
        self.mock_bd_cli.connect_sidecar.return_value = False

        actual = ActualState(
            physical_displays=[],
            main_display=None,
            ipad_usb_present=True,
            sidecar_connected=False,
        )
        self.engine.actual = actual
        self.engine.desired = DesiredState(
            target_display_role=DisplayRole.IPAD_MAIN,
            reason="Headless activation",
            needs_sidecar_connect=True,
        )

        # Trigger transition loop
        with patch("core.state_engine.notify_error") as mock_notify:
            self.engine._run_transition()
            self.assertGreater(self.engine.runtime.cooldown_until, time.time())
            mock_notify.assert_called_once()

    def test_scenario_7_sleep_wake(self) -> None:
        """Scenario 7: Wake event -> Evaluate state. If already satisfied, do not reconnect."""
        phys_disp = DisplayInfo(display_id=1, name="ASUS PG279Q", is_main=True)
        actual = ActualState(
            physical_displays=[phys_disp],
            main_display=phys_disp,
            ipad_usb_present=True,
            sidecar_connected=False,
        )
        self.mock_detector.observe.return_value = (actual, (((1,), True)))

        self.engine.evaluate(trigger="wake")
        self.mock_bd_cli.connect_sidecar.assert_not_called()
        self.mock_bd_cli.disconnect_sidecar.assert_not_called()

    def test_scenario_8_debounce_physical_display_flicker(self) -> None:
        """Scenario 8: Physical monitor flickers for 1s.
        Result: Debounce activates, does not switch to Sidecar. Monitor returns, cancels debounce.
        """
        now = time.time()
        # Physical disconnected
        active = self.engine.check_debounce(had_physical=True, now_has_physical=False)
        self.assertTrue(active)
        self.assertGreater(self.engine.runtime.debounce_until, now)

        actual = ActualState(
            physical_displays=[],
            main_display=None,
            ipad_usb_present=True,
        )
        desired = self.engine.policy(actual, self.config, self.engine.runtime)
        self.assertEqual(desired.target_display_role, DisplayRole.NO_CHANGE)
        self.assertIn("Waiting debounce", desired.reason)

        # Monitor returns within debounce window
        cancelled = self.engine.check_debounce(had_physical=False, now_has_physical=True)
        self.assertFalse(cancelled)
        self.assertEqual(self.engine.runtime.debounce_until, 0.0)

    def test_scenario_9_wireless_sidecar_respected(self) -> None:
        """Scenario 9: Physical monitor connected + ipad_usb_present = False + Sidecar active wirelessly
        Result: Automation respects wireless Sidecar as Secondary, does NOT demand USB, does NOT disconnect.
        """
        phys_disp = DisplayInfo(display_id=1, name="ASUS PG279Q", is_main=True)
        ipad_disp = DisplayInfo(display_id=2, name="Cayut iPad", is_main=False, is_sidecar=True)

        actual = ActualState(
            physical_displays=[phys_disp],
            main_display=phys_disp,
            ipad_usb_present=False,  # Wireless!
            sidecar_connected=True,
            sidecar_display_online=True,
        )

        desired = self.engine.policy(actual, self.config, self.engine.runtime)
        self.assertEqual(desired.target_display_role, DisplayRole.IPAD_SECONDARY)
        self.assertFalse(desired.needs_sidecar_disconnect)
        self.assertFalse(desired.needs_sidecar_connect)
        self.assertTrue(self.engine.is_satisfied(actual, desired))

    def test_scenario_10_zero_redundant_actions(self) -> None:
        """Scenario 10: Auto Mode + No physical display + USB iPad connected + Sidecar connected + iPad is Main
        Result: is_satisfied is True. connect_sidecar and set_main_display calls = 0. True DO NOTHING!
        """
        ipad_disp = DisplayInfo(display_id=2, name="Cayut iPad", is_main=True, is_sidecar=True)
        actual = ActualState(
            physical_displays=[],
            main_display=ipad_disp,
            ipad_usb_present=True,
            sidecar_connected=True,
            sidecar_display_online=True,
        )
        self.mock_detector.observe.return_value = (actual, (((), True)))

        self.engine.evaluate(trigger="periodic")

        self.assertEqual(self.mock_bd_cli.connect_sidecar.call_count, 0)
        self.assertEqual(self.mock_bd_cli.disconnect_sidecar.call_count, 0)
        self.assertEqual(self.mock_bd_cli.set_main_display.call_count, 0)

    def test_scenario_headless_sidecar_available_fallback_to_ipad_main(self) -> None:
        """Scenario: Headless + USB iPad delayed/missing + Sidecar available
        Result: Sidecar connects automatically via wireless/Continuity fallback, iPad set as Main.
        """
        actual = ActualState(
            physical_displays=[],
            main_display=None,
            ipad_usb_present=False,
            sidecar_available=True,
            sidecar_connected=False,
            sidecar_display_online=False,
        )
        desired = self.engine.policy(actual, self.config, self.engine.runtime)

        self.assertEqual(desired.target_display_role, DisplayRole.IPAD_MAIN)
        self.assertTrue(desired.needs_sidecar_connect)
        self.assertEqual(desired.needs_main_display_target, "ipad")
        self.assertIn("Sidecar Continuity/Wireless", desired.reason)
        self.assertFalse(self.engine.is_satisfied(actual, desired))

    def test_virtual_display_lifecycle_in_transitions(self) -> None:
        """Verify connect_virtual_display is called on virtual transition,
        and disconnect_virtual_display is called when switching to iPad/physical."""
        # 1. Transition to Virtual
        actual_headless = ActualState(
            physical_displays=[],
            main_display=None,
            virtual_display_exists=True,
            virtual_display_connected=False,
        )
        self.engine.actual = actual_headless
        self.engine.desired = DesiredState(
            target_display_role=DisplayRole.VIRTUAL,
            reason="Headless fallback",
            needs_main_display_target="virtual",
        )
        with patch("time.sleep"):
            self.engine._run_transition()
        self.mock_bd_cli.connect_virtual_display.assert_called_with("PadPilotVirtual")
        self.mock_bd_cli.set_main_display.assert_called_with("PadPilotVirtual")

        # 2. Transition from Virtual to iPad
        actual_virtual_online = ActualState(
            physical_displays=[],
            main_display=DisplayInfo(display_id=99, name="PadPilotVirtual", is_main=True, is_virtual=True),
            virtual_display_exists=True,
            virtual_display_connected=True,
            sidecar_connected=True,
            sidecar_display_online=True,
        )
        self.engine.actual = actual_virtual_online
        self.engine.desired = DesiredState(
            target_display_role=DisplayRole.IPAD_MAIN,
            reason="Switch to iPad Main",
            needs_sidecar_connect=False,
            needs_main_display_target="ipad",
        )
        ipad_main = DisplayInfo(display_id=2, name="Cayut iPad", is_main=True, is_sidecar=True)
        self.mock_detector.observe.return_value = (ActualState(
            main_display=ipad_main, sidecar_connected=True, sidecar_display_online=True,
            virtual_display_connected=True,
        ), ((), False))
        self.engine._run_transition()
        self.mock_bd_cli.disconnect_virtual_display.assert_called_with("PadPilotVirtual")

    def test_clear_user_override(self) -> None:
        """Verify clear_user_override clears override and falls back to PHYSICAL."""
        phys_disp = DisplayInfo(display_id=1, name="ROG PG279Q", is_main=True)
        self.engine.actual = ActualState(
            physical_displays=[phys_disp],
            main_display=phys_disp,
            sidecar_connected=False,
        )
        self.mock_detector.observe.return_value = (self.engine.actual, (((1,), False)))

        self.engine.set_user_override(DisplayRole.IPAD_SECONDARY, async_transition=False)
        self.assertIsNotNone(self.engine.runtime.user_override)

        self.engine.clear_user_override(async_transition=False)
        self.assertIsNone(self.engine.runtime.user_override)
        self.assertEqual(self.engine.desired.target_display_role, DisplayRole.PHYSICAL)
        self.assertFalse(self.engine.desired.needs_sidecar_connect)

    def test_sidecar_disconnect_with_physical_display_expires_override(self) -> None:
        """When Sidecar disconnects externally while a physical display is present,
        the iPad user override should expire and not force auto-reconnection."""
        phys_disp = DisplayInfo(display_id=1, name="ROG PG279Q", is_main=True)
        ipad_disp = DisplayInfo(display_id=2, name="Cayut iPad", is_main=False, is_sidecar=True)

        # 1. Connected state
        actual_connected = ActualState(
            physical_displays=[phys_disp],
            main_display=phys_disp,
            sidecar_connected=True,
            sidecar_display_online=True,
        )
        self.engine.actual = actual_connected
        self.engine.runtime.user_override = UserOverride(
            target_role=DisplayRole.IPAD_SECONDARY,
            topology_generation=0,
            timestamp=time.time(),
        )

        # 2. Sidecar disconnects externally (e.g. user locks iPad or disconnects via macOS/iPad)
        actual_disconnected = ActualState(
            physical_displays=[phys_disp],
            main_display=phys_disp,
            sidecar_connected=False,
            sidecar_display_online=False,
        )
        self.mock_detector.observe.return_value = (actual_disconnected, (((1,), False)))

        self.engine.evaluate(trigger="external_disconnect", async_transition=False)

        # Override must be expired
        self.assertIsNone(self.engine.runtime.user_override)
        self.assertEqual(self.engine.desired.target_display_role, DisplayRole.PHYSICAL)
        self.assertFalse(self.engine.desired.needs_sidecar_connect)
        self.assertTrue(self.engine.is_satisfied(actual_disconnected, self.engine.desired))


if __name__ == "__main__":
    unittest.main()
