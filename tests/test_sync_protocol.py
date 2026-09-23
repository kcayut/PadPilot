"""Tests for dual revision tracking, single writer architecture, and UI synchronization protocol."""

import io
import json
import runpy
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.config import Config, load_config, save_config
from core.models import (
    ActualState,
    DesiredState,
    DisplayInfo,
    DisplayRole,
    IpadConfig,
    OperationMode,
    StatusSnapshot,
    pairing_key,
)
from core.settings import ConflictError, apply_change
from core.state_engine import StateEngine

import copy

ROOT = Path(__file__).resolve().parents[1]
DAEMON = runpy.run_path(str(ROOT / "bin/sidecarswitchd"))
CLI = runpy.run_path(str(ROOT / "bin/sidecarswitch-cli"))
MENU = runpy.run_path(str(ROOT / "core/menu.py"))


class SyncProtocolTests(unittest.TestCase):
    """Test suite covering the 5 multi-process sync and concurrency invariants."""

    def setUp(self):
        self.config = Config(
            revision=1,
            mode=OperationMode.AUTOMATIC,
            ipad=IpadConfig(name="iPad Pro", sidecar_uuid="uuid-1234", usb_serial="usb-1234"),
            paired_ipads=[IpadConfig(name="iPad Pro", sidecar_uuid="uuid-1234", usb_serial="usb-1234")],
        )

    # 1. Watchdog evaluate unchanged does not increment status revision or write
    def test_watchdog_evaluate_unchanged_does_not_increment_status_revision_or_write(self):
        detector = MagicMock()
        bd_cli = MagicMock()
        engine = StateEngine(self.config, detector, bd_cli)

        dummy_actual = ActualState(
            physical_displays=[DisplayInfo(display_id="disp-1", name="Dell 4K", is_builtin=False, is_sidecar=False)],
            sidecar_connected=False,
            sidecar_available=False,
            main_display=DisplayInfo(display_id="disp-1", name="Dell 4K", is_builtin=False, is_sidecar=False),
        )
        detector.observe.return_value = (dummy_actual, (("disp-1",), False))

        with patch("core.state_engine.write_atomic_status") as mock_write_status, \
             patch("subprocess.run") as mock_subproc:

            # 1st evaluation: meaningful content exported, revision starts at 0 -> 1
            engine.evaluate(trigger="periodic")
            self.assertEqual(engine.status_revision, 1)
            self.assertEqual(mock_write_status.call_count, 1)

            # 2nd evaluation with identical state (watchdog tick)
            engine.evaluate(trigger="periodic")
            # Must NOT increment status_revision and must NOT write status.json again
            self.assertEqual(engine.status_revision, 1)
            self.assertEqual(mock_write_status.call_count, 1)

            # 3rd evaluation: meaningful change occurs (e.g. Sidecar connects)
            changed_actual = ActualState(
                physical_displays=[DisplayInfo(display_id="disp-1", name="Dell 4K", is_builtin=False, is_sidecar=False)],
                sidecar_connected=True,
                sidecar_available=True,
                main_display=DisplayInfo(display_id="disp-1", name="Dell 4K", is_builtin=False, is_sidecar=False),
            )
            detector.observe.return_value = (changed_actual, (("disp-1",), True))

            engine.evaluate(trigger="event")
            # Must increment status_revision and write status.json
            self.assertEqual(engine.status_revision, 2)
            self.assertEqual(mock_write_status.call_count, 2)

    def test_mode_change_exports_new_snapshot_without_launching_menu_processes(self):
        detector, bd = MagicMock(), MagicMock()
        engine = StateEngine(self.config, detector, bd)
        actual = ActualState(physical_displays=[DisplayInfo(1, 'Monitor')],
                             main_display=DisplayInfo(1, 'Monitor'))
        detector.observe.return_value = (actual, (('Monitor',), False))
        with patch('core.state_engine.write_atomic_status') as write, patch('subprocess.Popen') as launch:
            engine.evaluate()
            self.assertEqual(write.call_count, 1)
            engine.config.mode = OperationMode.MANUAL_ONLY
            engine.config.revision += 1
            engine.runtime.mode = OperationMode.MANUAL_ONLY
            engine.evaluate()
            self.assertEqual(write.call_count, 2)
            self.assertEqual(write.call_args.args[0].config_revision, engine.config.revision)
            launch.assert_not_called()

    # 2. Inconsistent revision snapshot does not mix stale reasons
    def test_inconsistent_revision_snapshot_does_not_mix_stale_reasons(self):
        from core.gui import read_view

        cfg = Config(revision=5, mode=OperationMode.MANUAL_ONLY)
        # Status snapshot is still at older config_revision=4
        stale_status = StatusSnapshot(
            timestamp=time.time(),
            mode="automatic",
            icon="green",
            actual={"sidecar_connected": False},
            desired={"target_display_role": "ipad_main", "reason": "Old automatic reasoning"},
            runtime={},
            configured_ipad={},
            summary_text="All good",
            status_details={"desired_role": "ipad_main", "reason": "Old automatic reasoning"},
            paired_ipads=[],
            config_revision=4,
            status_revision=10,
            topology_generation=0,
            evaluation_state="idle",
        )

        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = json.dumps(cfg.to_dict())

        with patch("core.gui.get_config_file_path", return_value=mock_path), \
             patch("core.gui.read_private_json", return_value=cfg.to_dict()), \
             patch("core.gui.read_status", return_value=stale_status.to_dict()):
            view = read_view(scan=False)

        # Inconsistency protocol must flag APPLYING_CONFIG
        self.assertEqual(view["consistency_state"], "APPLYING_CONFIG")
        self.assertEqual(view["config_revision"], 5)
        self.assertEqual(view["status_config_revision"], 4)
        self.assertEqual(view["status_revision"], 10)

        from core.gui import build_gui_payload
        with patch('core.gui.read_view', return_value=view), \
             patch('core.gui.BetterDisplayCLI.resolve_cli_path', return_value=None):
            payload = build_gui_payload()
            self.assertNotIn('Old automatic reasoning', str(payload['decision']))
            self.assertIn('套用新設定中', payload['decision']['reason'])
            view['consistency_state'] = 'REVISION_CONFLICT'
            payload = build_gui_payload()
            self.assertNotIn('Old automatic reasoning', str(payload['decision']))
            self.assertEqual(payload['decision']['satisfaction'], '不同步')


    # 5. Optimistic concurrency rejects stale expected revision
    def test_optimistic_concurrency_rejects_stale_expected_revision(self):
        cls = DAEMON["SidecarSwitchDaemon"]
        daemon = cls.__new__(cls)
        daemon.config = Config(revision=5, mode=OperationMode.AUTOMATIC)
        daemon.detector = MagicMock()
        daemon.engine = MagicMock()

        # 1. Daemon direct method check: stale expected_revision=4 against revision=5
        with patch.dict(cls.handle_client_cmd.__globals__, {"save_config": MagicMock()}):
            with self.assertRaises(ConflictError) as ctx:
                daemon.apply_config_change("set_mode", {"mode": "manual_only"}, expected_revision=4)
            self.assertIn("CONFIG_CONFLICT", str(ctx.exception))

            # 2. Daemon JSON IPC response check
            req = {
                "id": "req-1",
                "command": "set_mode",
                "params": {"mode": "manual_only"},
                "expected_revision": 4,
            }
            resp_str = daemon.handle_client_cmd(json.dumps(req))
            resp = json.loads(resp_str)
            self.assertFalse(resp["ok"])
            self.assertEqual(resp["error"], "CONFIG_CONFLICT")
            self.assertEqual(resp["config_revision"], 5)

            # 3. Success when expected_revision matches
            req["expected_revision"] = 5
            resp_str = daemon.handle_client_cmd(json.dumps(req))
            resp = json.loads(resp_str)
            self.assertTrue(resp["ok"])
            self.assertEqual(resp["config_revision"], 6)

        # 4. CLI submit_settings check: offline mutation conflict
        with patch.dict(CLI["submit_settings"].__globals__, {
            "send_daemon_cmd": MagicMock(return_value="Daemon is not running. (Socket not found)"),
            "load_config": MagicMock(return_value=Config(revision=8)),
            "save_config": MagicMock(),
        }):
            with self.assertRaises(RuntimeError) as ctx:
                CLI["submit_settings"]("set_mode", {"mode": "manual_only"}, expected_revision=7)
            self.assertIn("CONFIG_CONFLICT", str(ctx.exception))

    def test_menu_reads_fresh_config_and_rejects_mixed_revisions(self):
        config = Config(auto_detect_ipad=False, revision=2, mode=OperationMode.MANUAL_ONLY,
                        ipad=IpadConfig(name='New iPad Name'))
        status = {'config_revision': 2, 'timestamp': time.time(), 'actual': {'sidecar_devices': []},
                  'status_details': {'reason': 'Do not expose stale reasoning'}}
        for status_rev, expected in ((2, '運作中'), (1, '套用設定中…'), (3, '同步狀態重新讀取中…')):
            status['config_revision'] = status_rev
            rows = MENU['render'](status, config.to_dict(), True)['items']
            titles = [r['title'] for r in rows]
            self.assertIn('模式：僅手動｜' + expected, titles)
            self.assertIn('目前目標：New iPad Name', titles)
            modes = [r for r in rows if r['args'][:1] == ['set-mode'] and r['checked']]
            self.assertEqual([r['args'] for r in modes], [['set-mode', 'manual_only']])
            self.assertFalse(any('Do not expose' in title for title in titles))
            if status_rev != 2:
                self.assertFalse(any(r['enabled'] and r['args'][:1] == ['action']
                                     for r in rows if r['args'] != ['action', 'refresh']))

    # 9. Rename inactive iPad increments revision and saves without display transition
    def test_rename_inactive_ipad_increments_revision_and_saves_without_display_transition(self):
        cls = DAEMON["SidecarSwitchDaemon"]
        daemon = cls.__new__(cls)
        daemon.config_lock = threading.Lock()
        u1 = "00000000-0000-0000-0000-000000000001"
        u2 = "00000000-0000-0000-0000-000000000002"
        daemon.config = Config(
            revision=1,
            ipad=IpadConfig(name="Main iPad", sidecar_uuid=u1, usb_serial="USB-MAIN"),
            paired_ipads=[
                IpadConfig(name="Main iPad", sidecar_uuid=u1, usb_serial="USB-MAIN"),
                IpadConfig(name="Old Second iPad", sidecar_uuid=u2, usb_serial="USB-SECOND"),
            ],
        )
        daemon.detector = MagicMock()
        daemon.engine = MagicMock()

        mock_save = MagicMock()
        with patch.dict(cls.apply_config_change.__globals__, {
            "save_config": mock_save,
        }):
            needs_transition, new_cfg = daemon.apply_config_change(
                "save_pairing",
                {
                    "ipad": {"name": "New Second iPad Name", "sidecar_uuid": u2, "usb_serial": "USB-SECOND"},
                    "activate": False,
                },
            )

            # Display transition must NOT be triggered
            self.assertFalse(needs_transition)
            # Revision must be incremented
            self.assertEqual(new_cfg.revision, 2)
            # Config must be saved
            self.assertEqual(mock_save.call_count, 1)
            saved_cfg = mock_save.call_args[0][0]
            self.assertEqual(saved_cfg.revision, 2)
            self.assertEqual(saved_cfg.paired_ipads[1].name, "New Second iPad Name")


    # 11. Semantic config equality ignores revision and timestamp
    def test_semantic_config_equality_ignores_revision_and_timestamp(self):
        c1 = Config(revision=1, updated_at=100.0, mode=OperationMode.AUTOMATIC)
        c2 = Config(revision=2, updated_at=200.0, mode=OperationMode.AUTOMATIC)
        # Equality ignores revision and updated_at
        self.assertTrue(c1.content_equals(c2))
        self.assertEqual(c1.semantic_dict(), c2.semantic_dict())

        # Change in mode is detected
        c3 = Config(revision=1, updated_at=100.0, mode=OperationMode.MANUAL_ONLY)
        self.assertFalse(c1.content_equals(c3))

        # Change in paired iPads is detected
        c4 = copy.deepcopy(c1)
        c4.paired_ipads.append(IpadConfig(name="iPad Air", sidecar_uuid="uuid-999"))
        self.assertFalse(c1.content_equals(c4))

        # Non-Config comparison returns False safely
        self.assertFalse(c1.content_equals({"revision": 1}))


if __name__ == "__main__":
    unittest.main()
